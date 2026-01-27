import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import Any

import paho.mqtt.client as mqtt
import paho.mqtt.subscribeoptions
import structlog
from paho.mqtt.client import MQTT_CLEAN_START_FIRST_ONLY, MQTTMessage
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode, MQTTProtocolVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from updates2mqtt.model import Discovery, ReleaseProvider

from .config import HomeAssistantConfig, MqttConfig, NodeConfig, PublishPolicy
from .hass_formatter import hass_format_config, hass_format_state

log = structlog.get_logger()

MQTT_NAME = r"[A-Za-z0-9_\-\.]+"


@dataclass
class LocalMessage:
    topic: str | None = field(default=None)
    payload: str | None = field(default=None)


class MqttPublisher:
    def __init__(self, cfg: MqttConfig, node_cfg: NodeConfig, hass_cfg: HomeAssistantConfig) -> None:
        self.cfg: MqttConfig = cfg
        self.node_cfg: NodeConfig = node_cfg
        self.hass_cfg: HomeAssistantConfig = hass_cfg
        self.providers_by_topic: dict[str, ReleaseProvider] = {}
        self.providers_by_type: dict[str, ReleaseProvider] = {}
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.client: mqtt.Client | None = None
        self.fatal_failure = Event()
        self.log = structlog.get_logger().bind(host=cfg.host, integration="mqtt")

    def start(self, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        logger = self.log.bind(action="start")
        try:
            protocol: MQTTProtocolVersion
            if self.cfg.protocol in ("3", "3.11"):
                protocol = MQTTProtocolVersion.MQTTv311
            elif self.cfg.protocol == "3.1":
                protocol = MQTTProtocolVersion.MQTTv31
            elif self.cfg.protocol in ("5", "5.0"):
                protocol = MQTTProtocolVersion.MQTTv5
            else:
                logger.info("No valid MQTT protocol version found (%s), setting to default v3.11", self.cfg.protocol)
                protocol = MQTTProtocolVersion.MQTTv311
            logger.debug("MQTT protocol set to %r", protocol)

            self.event_loop = event_loop or asyncio.get_event_loop()
            self.client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=f"updates2mqtt_{self.node_cfg.name}",
                clean_session=True if protocol != MQTTProtocolVersion.MQTTv5 else None,
                protocol=protocol,
            )
            self.client.username_pw_set(self.cfg.user, password=self.cfg.password)
            rc: MQTTErrorCode = self.client.connect(
                host=self.cfg.host,
                port=self.cfg.port,
                keepalive=60,
                clean_start=MQTT_CLEAN_START_FIRST_ONLY,
            )
            logger.info("Client connection requested", result_code=rc)

            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            self.client.on_subscribe = self.on_subscribe
            self.client.on_unsubscribe = self.on_unsubscribe

            self.client.loop_start()

            logger.debug("MQTT Publisher loop started", host=self.cfg.host, port=self.cfg.port)
        except Exception as e:
            logger.error("Failed to connect to broker", host=self.cfg.host, port=self.cfg.port, error=str(e))
            raise OSError(f"Connection Failure to {self.cfg.host}:{self.cfg.port} as {self.cfg.user} -- {e}") from e

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def is_available(self) -> bool:
        return self.client is not None and not self.fatal_failure.is_set()

    def on_connect(
        self, _client: mqtt.Client, _userdata: Any, _flags: mqtt.ConnectFlags, rc: ReasonCode, _props: Properties | None
    ) -> None:
        if not self.client or self.fatal_failure.is_set():
            self.log.warn("No client, check if started and authorized")
            return
        if rc.getName() == "Not authorized":
            self.fatal_failure.set()
            log.error("Invalid MQTT credentials", result_code=rc)
            return
        if rc != 0:
            self.log.warning("Connection failed to broker", result_code=rc)
        else:
            self.log.debug("Connected to broker", result_code=rc)
            for topic, provider in self.providers_by_topic.items():
                self.log.debug("(Re)subscribing", topic=topic, provider=provider.source_type)
                self.client.subscribe(topic)

    def on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        rc: ReasonCode,
        _props: Properties | None,
    ) -> None:
        if rc == 0:
            self.log.debug("Disconnected from broker", result_code=rc)
        else:
            self.log.warning("Disconnect failure from broker", result_code=rc)

    async def clean_topics(
        self,
        provider: ReleaseProvider,
        _last_scan_session: str | None,
        wait_time: int = 5,
        max_time: int = 120,
        force: bool = False,
    ) -> None:
        logger = self.log.bind(action="clean")
        if self.fatal_failure.is_set():
            return
        try:
            logger.info("Starting clean cycle, max time: %s", max_time)
            cutoff_time: float = time.time() + max_time
            cleaner = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION1,
                client_id=f"updates2mqtt_clean_{self.node_cfg.name}",
                clean_session=True,
            )
            results = {"cleaned": 0, "handled": 0, "discovered": 0, "last_timestamp": time.time()}
            cleaner.username_pw_set(self.cfg.user, password=self.cfg.password)
            cleaner.connect(host=self.cfg.host, port=self.cfg.port, keepalive=60)

            def cleanup(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
                discovery: Discovery | None = None
                if msg.topic.startswith(
                    f"{self.hass_cfg.discovery.prefix}/update/{self.node_cfg.name}_{provider.source_type}_"
                ):
                    discovery = self.reverse_config_topic(msg.topic)
                    if discovery is None:
                        logger.info("Config topic discovery unknown", topic=msg.topic)
                elif msg.topic.startswith(
                    f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}/"
                ) and msg.topic.endswith("/state"):
                    discovery = self.reverse_state_topic(msg.topic)
                    if discovery is None:
                        logger.info("State topic discovery unknown", topic=msg.topic)
                elif msg.topic.startswith(f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}/"):
                    discovery = self.reverse_general_topic(msg.topic)
                    if discovery is None:
                        logger.info("General topic discovery unknown", topic=msg.topic)
                else:
                    logger.info("Unable to find matching discovery for topic", topic=msg.topic)

                results["discovered"] += 1
                results["handled"] += 1
                results["last_timestamp"] = time.time()
                if discovery is None and force:
                    logger.debug("Removing untrackable msg", topic=msg.topic)
                    cleaner.publish(msg.topic, "", retain=True)
                    results["cleaned"] += 1

            cleaner.on_message = cleanup
            options = paho.mqtt.subscribeoptions.SubscribeOptions(noLocal=True)
            cleaner.subscribe(f"{self.hass_cfg.discovery.prefix}/update/#", options=options)
            cleaner.subscribe(f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}/#", options=options)

            while time.time() - results["last_timestamp"] <= wait_time and time.time() <= cutoff_time:
                cleaner.loop(0.5)

            logger.info(
                f"Cleaned - discovered:{results['discovered']}, handled:{results['handled']}, cleaned:{results['cleaned']}"
            )
        except Exception as e:
            logger.error("Cleaning topics of stale entries failed: %s", e)

    def safe_json_decode(self, jsonish: str | bytes | None) -> dict:
        if jsonish is None:
            return {}
        try:
            return json.loads(jsonish)
        except Exception:
            log.exception("JSON decode fail (%s)", jsonish)
        try:
            return json.loads(jsonish[1:-1])
        except Exception:
            log.exception("JSON decode fail (%s)", jsonish[1:-1])
        return {}

    async def execute_command(
        self, msg: MQTTMessage | LocalMessage, on_update_start: Callable, on_update_end: Callable
    ) -> None:
        # TODO: defer handling of commands where repository is throttled
        logger = self.log.bind(topic=msg.topic, payload=msg.payload)
        comp_name: str | None = None
        command: str | None = None
        try:
            logger.info("Execution starting")
            source_type: str | None = None

            payload: str | None = None
            if isinstance(msg.payload, bytes):
                payload = msg.payload.decode("utf-8")
            elif isinstance(msg.payload, str):
                payload = msg.payload
            if payload and "|" in payload:
                source_type, comp_name, command = payload.split("|")

            provider: ReleaseProvider | None = self.providers_by_topic.get(msg.topic) if msg.topic else None
            if not provider:
                logger.warn("Unexpected provider type %s", msg.topic)
            elif provider.source_type != source_type:
                logger.warn("Unexpected source type %s", source_type)
            elif command != "install" or not comp_name:
                logger.warn("Invalid payload in command message: %s", msg.payload)
            else:
                logger.info(
                    "Passing %s command to %s scanner for %s",
                    command,
                    source_type,
                    comp_name,
                )
                updated: bool = provider.command(comp_name, command, on_update_start, on_update_end)
                discovery = provider.resolve(comp_name)
                if updated and discovery:
                    if discovery.publish_policy == PublishPolicy.HOMEASSISTANT and self.hass_cfg.discovery.enabled:
                        self.publish_hass_config(discovery)
                    if discovery.publish_policy in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT):
                        self.publish_discovery(discovery)
                    if discovery.publish_policy == PublishPolicy.HOMEASSISTANT:
                        self.publish_hass_state(discovery)
                else:
                    logger.debug("No change to republish after execution")
            logger.info("Execution ended")
        except Exception:
            logger.exception("Execution failed", component=comp_name, command=command)

    def local_message(self, discovery: Discovery, command: str) -> None:
        """Simulate an incoming MQTT message for local commands"""
        msg = LocalMessage(
            topic=self.command_topic(discovery.provider), payload="|".join([discovery.source_type, discovery.name, command])
        )
        self.handle_message(msg)

    def on_subscribe(
        self,
        _client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: list[ReasonCode],
        properties: Properties | None = None,
    ) -> None:
        self.log.debug(
            "on_subscribe, userdata=%s, mid=%s, reasons=%s, properties=%s", userdata, mid, reason_code_list, properties
        )

    def on_unsubscribe(
        self,
        _client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: list[ReasonCode],
        properties: Properties | None = None,
    ) -> None:
        self.log.debug(
            "on_unsubscribe, userdata=%s, mid=%s, reasons=%s, properties=%s", userdata, mid, reason_code_list, properties
        )

    def on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback for incoming MQTT messages"""  # noqa: D401
        if msg.topic in self.providers_by_topic:
            self.handle_message(msg)
        else:
            # apparently the root non-wildcard sub sometimes brings in child topics
            self.log.debug("Unhandled message #%s on %s:%s", msg.mid, msg.topic, msg.payload)

    def handle_message(self, msg: mqtt.MQTTMessage | LocalMessage) -> None:
        def update_start(discovery: Discovery) -> None:
            if discovery.publish_policy in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT):
                self.publish_hass_state(discovery, in_progress=True)

        def update_end(discovery: Discovery) -> None:
            if discovery.publish_policy in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT):
                self.publish_hass_state(discovery, in_progress=False)

        if self.event_loop is not None:
            asyncio.run_coroutine_threadsafe(self.execute_command(msg, update_start, update_end), self.event_loop)
        else:
            self.log.error("No event loop to handle message", topic=msg.topic)

    def config_topic(self, discovery: Discovery) -> str:
        prefix = self.hass_cfg.discovery.prefix
        return f"{prefix}/update/{self.node_cfg.name}_{discovery.source_type}_{discovery.name}/update/config"

    def _provider_type_match(self) -> str:
        return "|".join(t for t in self.providers_by_type)

    def reverse_config_topic(self, topic: str) -> Discovery | None:
        match = re.fullmatch(
            f"{self.hass_cfg.discovery.prefix}/update/{self.node_cfg.name}:({self._provider_type_match}):({MQTT_NAME})/update/config",
            topic,
        )
        if match:
            self.log.debug("CONFIG %s groups: %s", len(match.groups()), match.groups())
        else:
            self.log.debug("NO MATCH CONFIG")

        if match and len(match.groups()) == 2:
            discovery_type: str = match.group(1)
            discovery_name: str = match.group(2)
            if (
                discovery_type in self.providers_by_type
                and discovery_name in self.providers_by_type[discovery_type].discoveries
            ):
                return self.providers_by_type[discovery_type].discoveries[discovery_name]
            self.log.debug("CONFIG discovery_type in providers_by_type: %s", bool(discovery_type in self.providers_by_type))
            self.log.debug(list(self.providers_by_type.keys()))
            self.log.debug("CONFIG Can't find %s for %s in %s", discovery_name, discovery_type, topic)
        else:
            self.log.debug("CONFIG no match for %s", topic)
        return None

    def state_topic(self, discovery: Discovery) -> str:
        return f"{self.cfg.topic_root}/{self.node_cfg.name}/{discovery.source_type}/{discovery.name}/state"

    def reverse_state_topic(self, topic: str) -> Discovery | None:
        match = re.fullmatch(
            f"{self.cfg.topic_root}/{self.node_cfg.name}/({self._provider_type_match})/({MQTT_NAME})/state",
            topic,
        )
        if match:
            self.log.debug("STATE %s groups: %s", len(match.groups()), match.groups())
        else:
            self.log.debug(
                "NO MATCH STATE for %s by %s",
                topic,
                f"{self.cfg.topic_root}/{self.node_cfg.name}/({self._provider_type_match})/({MQTT_NAME})/state",
            )
        if match and len(match.groups()) == 2:
            discovery_type: str = match.group(1)
            discovery_name: str = match.group(2)
            if (
                discovery_type in self.providers_by_type
                and discovery_name in self.providers_by_type[discovery_type].discoveries
            ):
                return self.providers_by_type[discovery_type].discoveries[discovery_name]
        return None

    def general_topic(self, discovery: Discovery) -> str:
        return f"{self.cfg.topic_root}/{self.node_cfg.name}/{discovery.source_type}/{discovery.name}"

    def reverse_general_topic(self, topic: str) -> Discovery | None:
        match = re.fullmatch(f"{self.cfg.topic_root}/{self.node_cfg.name}/({self._provider_type_match})/({MQTT_NAME})", topic)
        if match and len(match.groups()) == 2:
            discovery_type: str = match.group(1)
            discovery_name: str = match.group(2)
            if (
                discovery_type in self.providers_by_type
                and discovery_name in self.providers_by_type[discovery_type].discoveries
            ):
                return self.providers_by_type[discovery_type].discoveries[discovery_name]
        return None

    def command_topic(self, provider: ReleaseProvider) -> str:
        return f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}"

    def publish_discovery(self, discovery: Discovery, in_progress: bool = False) -> None:
        """Comprehensive, non Home Assistant specific, base publication"""
        if discovery.publish_policy not in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT):
            return
        self.log.debug("Discovery publish: %s", discovery)
        payload: dict[str, Any] = discovery.as_dict()
        payload["update"]["in_progress"] = in_progress  # ty:ignore[invalid-assignment]
        self.publish(self.general_topic(discovery), payload)

    def publish_hass_state(self, discovery: Discovery, in_progress: bool = False) -> None:
        if discovery.publish_policy != PublishPolicy.HOMEASSISTANT:
            return
        self.log.debug("HASS State update, in progress: %s, discovery: %s", in_progress, discovery)
        self.publish(
            self.state_topic(discovery),
            hass_format_state(
                discovery,
                discovery.session,
                in_progress=in_progress,
            ),
        )

    def publish_hass_config(self, discovery: Discovery) -> None:
        if discovery.publish_policy != PublishPolicy.HOMEASSISTANT:
            return
        object_id = f"{discovery.source_type}_{self.node_cfg.name}_{discovery.name}"
        self.log.debug("HASS Config: %s", object_id)

        self.publish(
            self.config_topic(discovery),
            hass_format_config(
                discovery=discovery,
                object_id=object_id,
                area=self.hass_cfg.area,
                state_topic=self.state_topic(discovery),
                attrs_topic=self.general_topic(discovery) if self.hass_cfg.extra_attributes else None,
                command_topic=self.command_topic(discovery.provider),
                force_command_topic=self.hass_cfg.force_command_topic,
                device_creation=self.hass_cfg.device_creation,
            ),
        )

    def subscribe_hass_command(self, provider: ReleaseProvider):  # noqa: ANN201
        topic = self.command_topic(provider)
        if topic in self.providers_by_topic or self.client is None:
            self.log.debug("Skipping subscription", topic=topic)
        else:
            self.log.info("Handler subscribing", topic=topic)
            self.providers_by_topic[topic] = provider
            self.providers_by_type[provider.source_type] = provider
            self.client.subscribe(topic)
        return topic

    def loop_once(self) -> None:
        if self.client:
            self.client.loop()

    def publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = True) -> None:
        if self.client:
            self.client.publish(topic, payload=json.dumps(payload), qos=qos, retain=retain)
