"""Edge paths of the MQTT publisher: topic cleaning payloads, command validation and publish policies"""

import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import paho.mqtt.client
import pytest
from omegaconf import OmegaConf
from paho.mqtt.enums import MQTTErrorCode

from updates2mqtt.config import HomeAssistantConfig, MqttConfig, NodeConfig, PublishPolicy
from updates2mqtt.model import Discovery, ReleaseDetail, ReleaseProvider
from updates2mqtt.mqtt import LocalMessage, MqttPublisher

NODE = "cleannode"


def new_publisher() -> MqttPublisher:
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = NODE
    return MqttPublisher(OmegaConf.structured(MqttConfig), node_config, OmegaConf.structured(HomeAssistantConfig))


@pytest.fixture
def uut(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> Iterator[MqttPublisher]:
    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        publisher = new_publisher()
        publisher.start(event_loop=Mock())
        publisher.subscribe_hass_command(mock_provider)
        yield publisher


def discovery_of(provider: ReleaseProvider, name: str = "fooey", **kwargs: Any) -> Discovery:
    return Discovery(provider, name, session="s1", node=NODE, current_version="v1", latest_version="v2", **kwargs)


# === connection ===


def test_start_times_out_waiting_for_broker() -> None:
    silent_client = MagicMock(spec=paho.mqtt.client.Client)
    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: silent_client):
        publisher = new_publisher()
        publisher.cfg.connect_timeout = 0.2
        publisher.start(event_loop=Mock())
    assert not publisher.connected.is_set()
    # carries on regardless, as paho keeps retrying
    assert publisher.is_available()


def test_publish_availability_needs_client() -> None:
    with pytest.raises(ValueError, match="No MQTT client"):
        new_publisher().publish_availability(online=True)


def test_subscribe_callbacks_only_log(uut: MqttPublisher) -> None:
    uut.on_subscribe(Mock(), None, 1, [])
    uut.on_unsubscribe(Mock(), None, 2, [])


def test_publish_queues_when_disconnected(uut: MqttPublisher, mock_mqtt_client: Mock) -> None:
    for rc in (MQTTErrorCode.MQTT_ERR_NO_CONN, MQTTErrorCode.MQTT_ERR_QUEUE_SIZE):
        mock_mqtt_client.publish.return_value = Mock(rc=rc, mid=7)
        uut.publish("some/topic", {"a": 1})
    assert mock_mqtt_client.publish.call_count >= 2


# === topic cleaning ===


def run_clean(uut: MqttPublisher, provider: ReleaseProvider, messages: list[tuple[str, Any]], initial: bool = False) -> Mock:
    """Clean with a fake cleaner client that delivers the given retained messages on its first loop"""
    cleaner = Mock()

    def deliver(_timeout: float) -> None:
        if cleaner.loop.call_count == 1:
            for topic, payload in messages:
                msg = Mock(topic=topic, payload=payload)
                cleaner.on_message(cleaner, None, msg)
        else:
            uut.stopping.set()

    cleaner.loop.side_effect = deliver
    with patch("updates2mqtt.mqtt.mqtt.Client", return_value=cleaner):
        uut.clean_topics_blocking(provider, wait_time=5, max_time=10, initial=initial)
    uut.stopping.clear()
    return cleaner


def published(cleaner: Mock) -> dict[str, Any]:
    return {c.args[0]: c.args[1] for c in cleaner.publish.call_args_list}


def test_clean_state_and_attribute_topics(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    base = f"updates2mqtt/{NODE}/unit_test"
    cleaner = run_clean(
        uut,
        mock_provider,
        [
            (f"{base}/fooey/state", b'{"installed_version": "v1", "latest_version": "v2"}'),
            (f"{base}/gone/state", b'{"installed_version": "v1", "latest_version": "v2"}'),
            (f"{base}/fooey", b'{"name": "fooey"}'),
            (f"{base}/gone", b'{"name": "gone"}'),
            (f"{base}/odd/topic/shape", None),
            ("homeassistant/update/othernode_thing/update/config", b"{}"),
        ],
    )
    assert published(cleaner) == {f"{base}/gone/state": "", f"{base}/gone": "", f"{base}/odd/topic/shape": ""}


def test_clean_initial_clears_lingering_in_progress(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    base = f"updates2mqtt/{NODE}/unit_test"
    cleaner = run_clean(
        uut,
        mock_provider,
        [
            (f"{base}/fooey/state", b'{"installed_version": "v1", "latest_version": "v2", "in_progress": true}'),
            (f"{base}/fooey", b'{"name": "fooey", "update": {"in_progress": true}}'),
        ],
        initial=True,
    )
    republished = {topic: json.loads(payload) for topic, payload in published(cleaner).items()}
    assert republished[f"{base}/fooey/state"]["in_progress"] is False
    assert republished[f"{base}/fooey"]["update"]["in_progress"] is False


def test_clean_initial_clears_incomplete_state_and_bad_json(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    base = f"updates2mqtt/{NODE}/unit_test"
    cleaner = run_clean(
        uut,
        mock_provider,
        [
            (f"{base}/fooey/state", b'{"installed_version": "v1"}'),
            (f"{base}/fooey", b"{not json"),
            # unknown discoveries survive the initial clean, as the first scan hasn't run yet
            (f"{base}/later/state", b'{"installed_version": "v1", "latest_version": "v1"}'),
        ],
        initial=True,
    )
    assert published(cleaner) == {f"{base}/fooey/state": "", f"{base}/fooey": ""}


def test_clean_survives_client_failure(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    with patch("updates2mqtt.mqtt.mqtt.Client", side_effect=OSError("broker gone")):
        uut.clean_topics_blocking(mock_provider, wait_time=1, max_time=1)


def test_reverse_config_topic_unknown_provider(uut: MqttPublisher) -> None:
    assert uut.reverse_config_topic(f"homeassistant/update/{NODE}_other_fooey/update/config", "other") is None
    assert uut.reverse_config_topic("not/a/config/topic", "unit_test") is None


# === command validation ===


def command(topic: str | None, payload: Any) -> LocalMessage:
    msg = LocalMessage(topic=topic)
    msg.payload = payload
    return msg


@pytest.mark.parametrize(
    "msg",
    [
        command("updates2mqtt/cleannode/elsewhere", "unit_test|fooey|install"),
        command(None, "unit_test|fooey|install"),
        command("updates2mqtt/cleannode/unit_test", "unit_test|fooey|restart"),
        command("updates2mqtt/cleannode/unit_test", "unit_test||install"),
        command("updates2mqtt/cleannode/unit_test", "too|many|parts|here"),
        command("updates2mqtt/cleannode/unit_test", 42),
    ],
    ids=["unknown_topic", "no_topic", "unknown_command", "no_name", "malformed", "not_text"],
)
def test_validate_command_rejects(uut: MqttPublisher, msg: LocalMessage) -> None:
    assert uut.validate_command(msg) is None
    assert uut.commands_in_progress == set()


def test_validate_command_accepts_str_payload(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    parsed = uut.validate_command(command("updates2mqtt/cleannode/unit_test", "unit_test|fooey|install"))
    assert parsed == (mock_provider, "fooey", "install")


def test_handle_message_without_event_loop(mock_provider: ReleaseProvider) -> None:
    publisher = new_publisher()
    publisher.handle_message(command("updates2mqtt/cleannode/unit_test", "unit_test|fooey|install"))
    assert publisher.commands_in_progress == set()


# === command execution ===


async def test_execute_command_no_change(uut: MqttPublisher, mock_provider: ReleaseProvider, mock_mqtt_client: Mock) -> None:
    mock_provider.command.return_value = False  # type: ignore[attr-defined]
    mock_mqtt_client.publish.reset_mock()
    await uut.execute_command(mock_provider, "fooey", "install", Mock(), Mock())
    mock_mqtt_client.publish.assert_not_called()


async def test_execute_command_survives_provider_failure(uut: MqttPublisher, mock_provider: ReleaseProvider) -> None:
    mock_provider.command.side_effect = RuntimeError("pull failed")  # type: ignore[attr-defined]
    uut.commands_in_progress.add(("unit_test", "fooey"))
    await uut.execute_command(mock_provider, "fooey", "install", Mock(), Mock())
    assert uut.commands_in_progress == set()


async def test_handle_message_reports_progress(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    progress: list[str] = []

    async def install(
        _name: str, _command: str, on_start: Callable[[Discovery], None], on_end: Callable[[Discovery], None]
    ) -> bool:
        for policy in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT, PublishPolicy.SILENT):
            discovery = discovery_of(mock_provider, publish_policy=policy)
            on_start(discovery)
            on_end(discovery)
        progress.append("done")
        return True

    mock_provider.command.side_effect = install  # type: ignore[attr-defined]
    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        publisher = new_publisher()
        publisher.start(event_loop=asyncio.get_running_loop())
        publisher.subscribe_hass_command(mock_provider)
    mock_mqtt_client.publish.reset_mock()
    publisher.handle_message(command("updates2mqtt/cleannode/unit_test", "unit_test|fooey|install"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if progress and not publisher.command_tasks:
            break
    assert progress == ["done"]
    in_progress_flags = [
        json.loads(c.kwargs["payload"]).get("in_progress", json.loads(c.kwargs["payload"]).get("update", {}).get("in_progress"))
        for c in mock_mqtt_client.publish.call_args_list
    ]
    # state and attributes for HomeAssistant, attributes only for MQTT, nothing for silent
    assert in_progress_flags[:6] == [True, True, False, False, True, False]


# === publish policies ===


def test_silent_discoveries_not_published(uut: MqttPublisher, mock_provider: ReleaseProvider, mock_mqtt_client: Mock) -> None:
    mock_mqtt_client.publish.reset_mock()
    silent = discovery_of(mock_provider, publish_policy=PublishPolicy.SILENT)
    uut.publish_discovery(silent)
    uut.publish_hass_state(silent)
    uut.publish_hass_config(silent)
    mock_mqtt_client.publish.assert_not_called()


def test_publish_discovery_truncates_release_summary(
    uut: MqttPublisher, mock_provider: ReleaseProvider, mock_mqtt_client: Mock
) -> None:
    uut.hass_cfg.release_summary_max_size = 10
    discovery = discovery_of(mock_provider, release_detail=ReleaseDetail(summary="x" * 100))
    uut.publish_discovery(discovery)
    payload = json.loads(mock_mqtt_client.publish.call_args.kwargs["payload"])
    assert payload["release"]["summary"] == "x" * 10
