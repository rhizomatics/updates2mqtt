import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import paho.mqtt.client as mqtt
import paho.mqtt.subscribeoptions
import structlog
from paho.mqtt.client import MQTTMessage
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from updates2mqtt.model import Discovery, ReleaseProvider

from .config import HomeAssistantConfig, MqttConfig, NodeConfig
from .hass_formatter import hass_format_config, hass_format_state

log = structlog.get_logger()


@dataclass
class LocalMessage:
    topic: str | None = field(default=None)
    payload: str | None = field(default=None)


class MqttClient:
    def __init__(self, cfg: MqttConfig, node_cfg: NodeConfig, hass_cfg: HomeAssistantConfig) -> None:
        self.cfg: MqttConfig = cfg
        self.node_cfg: NodeConfig = node_cfg
        self.hass_cfg: HomeAssistantConfig = hass_cfg
        self.providers_by_topic: dict[str, ReleaseProvider] = {}
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.client: mqtt.Client | None = None
        self.log = structlog.get_logger().bind(host=cfg.host, integration="mqtt")

    def start(self, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        logger = self.log.bind(action="start")
        try:
            self.event_loop = event_loop or asyncio.get_event_loop()
            self.client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=f"updates2mqtt_{self.node_cfg.name}",
                clean_session=True,
            )
            self.client.username_pw_set(self.cfg.user, password=self.cfg.password)
            self.client.connect(host=self.cfg.host, port=self.cfg.port, keepalive=60)

            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message

            self.client.loop_start()

            logger.info("Connected to broker", host=self.cfg.host, port=self.cfg.port)
        except Exception as e:
            logger.error("Failed to connect to broker", host=self.cfg.host, port=self.cfg.port, error=str(e))
            raise OSError(f"Connection Failure to {self.cfg.host}:{self.cfg.port} as {self.cfg.user} -- {e}") from e

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def on_connect(
        self, _client: mqtt.Client, _userdata: Any, _flags: mqtt.ConnectFlags, rc: ReasonCode, _props: Properties | None
    ) -> None:
        if not self.client:
            self.log.warn("No client, check if started")
            return
        self.log.info("Connected to broker", result_code=rc)
        for topic in self.providers_by_topic:
            self.log.info("(Re)subscribing", topic=topic)
            self.client.subscribe(topic)

    def on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        rc: ReasonCode,
        _props: Properties | None,
    ) -> None:
        self.log.info("Disconnected from broker", result_code=rc)

    async def clean_topics(
        self, provider: ReleaseProvider, last_scan_session: str | None, wait_time: int = 5, force: bool = False
    ) -> None:
        logger = self.log.bind(action="clean")
        logger.info("Starting clean cycle")
        cleaner = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION1,
            client_id=f"updates2mqtt_clean_{self.node_cfg.name}",
            clean_session=True,
        )
        results = {"cleaned": 0, "handled": 0, "discovered": 0, "last_timestamp": time.time()}
        cleaner.username_pw_set(self.cfg.user, password=self.cfg.password)
        cleaner.connect(host=self.cfg.host, port=self.cfg.port, keepalive=60)
        prefixes = [
            f"{self.hass_cfg.discovery.prefix}/update/{self.node_cfg.name}_{provider.source_type}_",
            f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}/",
        ]

        def cleanup(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
            if msg.retain and any(msg.topic.startswith(prefix) for prefix in prefixes):
                session = None
                results["discovered"] += 1
                try:
                    payload = self.safe_json_decode(msg.payload)
                    session = payload.get("source_session")
                except Exception as e:
                    log.warn(
                        "Unable to handle payload for %s: %s",
                        msg.topic,
                        e,
                        exc_info=1,
                    )
                results["handled"] += 1
                results["last_timestamp"] = time.time()
                if session is not None and last_scan_session is not None and session != last_scan_session:
                    log.debug("Removing stale msg", topic=msg.topic, session=session)
                    cleaner.publish(msg.topic, "", retain=True)
                    results["cleaned"] += 1
                elif session is None and force:
                    log.debug("Removing untrackable msg", topic=msg.topic)
                    cleaner.publish(msg.topic, "", retain=True)
                    results["cleaned"] += 1
                else:
                    log.debug(
                        "Retaining topic with current session: %s",
                        msg.topic,
                    )
            else:
                log.debug("Skipping clean of %s", msg.topic)

        cleaner.on_message = cleanup
        options = paho.mqtt.subscribeoptions.SubscribeOptions(noLocal=True)
        cleaner.subscribe(f"{self.hass_cfg.discovery.prefix}/update/#", options=options)
        cleaner.subscribe(f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}/#", options=options)

        while time.time() - results["last_timestamp"] <= wait_time:
            cleaner.loop(0.5)

        log.info(
            f"Clean completed, discovered:{results['discovered']}, handled:{results['handled']}, cleaned:{results['cleaned']}"
        )

    def safe_json_decode(self, jsonish: str | bytes | None) -> dict:
        if jsonish is None:
            return {}
        try:
            return json.loads(jsonish)
        except Exception:
            log.exception("JSON decode fail (%s); %s", jsonish)
        try:
            return json.loads(jsonish[1:-1])
        except Exception:
            log.exception("JSON decode fail (%s): %s", jsonish[1:-1])
        return {}

    async def execute_command(
        self, msg: MQTTMessage | LocalMessage, on_update_start: Callable, on_update_end: Callable
    ) -> None:
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
                updated = provider.command(comp_name, command, on_update_start, on_update_end)
                discovery = provider.resolve(comp_name)
                if updated and discovery:
                    self.publish_hass_state(discovery, updated)
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

    def on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback for incoming MQTT messages"""  # noqa: D401
        if msg.topic in self.providers_by_topic:
            self.handle_message(msg)
        else:
            self.log.warn("Unhandled message: %s", msg.topic)

    def handle_message(self, msg: mqtt.MQTTMessage | LocalMessage) -> None:
        def update_start(discovery: Discovery) -> None:
            self.publish_hass_state(discovery, in_progress=True)

        def update_end(discovery: Discovery) -> None:
            self.publish_hass_state(discovery, in_progress=False)

        if self.event_loop is not None:
            asyncio.run_coroutine_threadsafe(self.execute_command(msg, update_start, update_end), self.event_loop)
        else:
            self.log.error("No event loop to handle message", topic=msg.topic)

    def config_topic(self, discovery: Discovery) -> str:
        prefix = self.hass_cfg.discovery.prefix
        return f"{prefix}/update/{self.node_cfg.name}_{discovery.source_type}_{discovery.name}/update/config"

    def state_topic(self, discovery: Discovery) -> str:
        return f"{self.cfg.topic_root}/{self.node_cfg.name}/{discovery.source_type}/{discovery.name}"

    def command_topic(self, provider: ReleaseProvider) -> str:
        return f"{self.cfg.topic_root}/{self.node_cfg.name}/{provider.source_type}"

    def publish_hass_state(self, discovery: Discovery, in_progress: bool = False) -> None:
        self.log.debug("HASS State update, in progress: %s, discovery: %s", in_progress, discovery)
        self.publish(
            self.state_topic(discovery),
            hass_format_state(
                discovery,
                self.node_cfg.name,
                discovery.session,
                in_progress=in_progress,
            ),
        )

    def publish_hass_config(self, discovery: Discovery) -> None:
        object_id = f"{discovery.source_type}_{self.node_cfg.name}_{discovery.name}"
        command_topic: str | None = self.command_topic(discovery.provider) if discovery.can_update else None
        self.publish(
            self.config_topic(discovery),
            hass_format_config(
                discovery,
                object_id,
                self.node_cfg.name,
                self.state_topic(discovery),
                command_topic,
                discovery.session,
            ),
        )

    def subscribe_hass_command(self, provider: ReleaseProvider):  # noqa: ANN201
        topic = self.command_topic(provider)
        if topic in self.providers_by_topic or self.client is None:
            self.log.debug("Skipping subscription", topic=topic)
        else:
            self.log.info("Handler subscribing", topic=topic)
            self.providers_by_topic[topic] = provider
            self.client.subscribe(topic)
        return topic

    def loop_once(self) -> None:
        if self.client:
            self.client.loop()

    def publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = True) -> None:
        if self.client:
            self.client.publish(topic, payload=json.dumps(payload), qos=qos, retain=retain)
