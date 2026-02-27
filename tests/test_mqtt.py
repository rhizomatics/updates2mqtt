import asyncio
import json
import time
from unittest import mock
from unittest.mock import Mock, patch

import paho.mqtt.client
import pytest
from omegaconf import OmegaConf
from paho.mqtt.client import MQTTMessage
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from updates2mqtt.config import HomeAssistantConfig, MqttConfig, NodeConfig
from updates2mqtt.model import Discovery, ReleaseProvider
from updates2mqtt.mqtt import MqttPublisher


@pytest.mark.parametrize("protocol", ["3", "3.1", "5", "?"])
def test_publish(mock_mqtt_client: Mock, protocol: str, node_cfg: NodeConfig) -> None:
    config = MqttConfig(protocol=protocol)
    hass_config = HomeAssistantConfig()

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_cfg, hass_config)
        uut.start()

        uut.publish("test.topic.123", {"foo": "a8", "bar": False})
        mock_mqtt_client.connect.assert_called_once()
        mock_mqtt_client.publish.assert_called_with("test.topic.123", payload='{"foo": "a8", "bar": false}', qos=0, retain=True)


@pytest.mark.asyncio
async def test_handler(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "testing"
    with patch("updates2mqtt.mqtt.mqtt.Client", new=mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start(event_loop=asyncio.get_running_loop())

        provider = Mock(spec=ReleaseProvider)
        provider.source_type = "unit_test"
        discovery = Discovery(provider, "qux", "test-mqtt-123", "node004")
        provider.command.return_value = discovery

        topic_name = uut.subscribe_hass_command(provider)
        mock_message = Mock()
        mock_message.topic = topic_name
        mock_message.payload = "|".join([provider.source_type, "qux", "install"])
        uut.handle_message(mock_message)

        cutoff = time.time() + 10
        while time.time() <= cutoff and not provider.command.called:  # noqa: ASYNC110
            await asyncio.sleep(0.5)

        provider.command.assert_called_with("qux", "install", mock.ANY, mock.ANY)


async def test_execute_command_remote(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "TESTBED"

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.providers_by_topic = {}
        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)

        mqtt_bytes_msg = MQTTMessage(topic=b"updates2mqtt/TESTBED/unit_test")
        mqtt_bytes_msg.payload = b"unit_test|fooey|install"
        await uut.execute_command(mqtt_bytes_msg, Mock(), Mock())

        mock_mqtt_client.publish.assert_called_with(
            "updates2mqtt/TESTBED/unit_test/fooey/state",
            payload=json.dumps(
                {
                    "installed_version": "v2",
                    "latest_version": "v2",
                    "title": "Update for fooey on node002",
                    "in_progress": False,
                }
            ),
            qos=0,
            retain=True,
        )


@pytest.mark.asyncio
async def test_execute_command_local(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "TESTBED"

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)

        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)

        discovery = mock_provider.resolve("test")
        assert discovery is not None
        uut.local_message(discovery, "install")
        await asyncio.sleep(1)

        mock_mqtt_client.publish.assert_called_with(
            "updates2mqtt/TESTBED/unit_test/fooey/state",
            payload=json.dumps(
                {
                    "installed_version": "v2",
                    "latest_version": "v2",
                    "title": "Update for fooey on node002",
                    "in_progress": False,
                }
            ),
            qos=0,
            retain=True,
        )


@pytest.mark.asyncio
async def test_stop(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)

        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)

        uut.stop()
        await asyncio.sleep(1)
        mock_mqtt_client.loop_stop.assert_called()
        mock_mqtt_client.disconnect.assert_called()


def test_is_available_when_connected(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        assert uut.is_available() is True


def test_is_available_when_not_started() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    assert uut.is_available() is False


def test_is_available_when_fatal_failure(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.fatal_failure.set()

        assert uut.is_available() is False


def test_on_connect_success(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.subscribe_hass_command(mock_provider)

        # Reset mock to track resubscription
        mock_mqtt_client.subscribe.reset_mock()

        rc = ReasonCode(PacketTypes.CONNACK, "Success")
        uut.on_connect(mock_mqtt_client, None, Mock(), rc, None)

        # Should resubscribe to all topics
        mock_mqtt_client.subscribe.assert_called()


def test_on_connect_not_authorized(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        # Simulate "Not authorized" connection failure with mock ReasonCode
        rc = Mock()
        rc.getName.return_value = "Not authorized"
        uut.on_connect(mock_mqtt_client, None, Mock(), rc, None)

        assert uut.fatal_failure.is_set()


def test_on_disconnect_success(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        rc = ReasonCode(PacketTypes.DISCONNECT, "Success")
        # Should not raise
        uut.on_disconnect(mock_mqtt_client, None, Mock(), rc, None)


def test_on_message_known_topic(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "testnode"

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start(event_loop=asyncio.new_event_loop())

        topic = uut.subscribe_hass_command(mock_provider)

        msg = Mock()
        msg.topic = topic
        msg.payload = b"unit_test|comp|install"
        msg.mid = 1

        with patch.object(uut, "handle_message") as mock_handle:
            uut.on_message(mock_mqtt_client, None, msg)
            mock_handle.assert_called_once_with(msg)


def test_on_message_unknown_topic(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start(event_loop=asyncio.new_event_loop())

        msg = Mock()
        msg.topic = "unknown/topic"
        msg.payload = b"some payload"
        msg.mid = 1

        with patch.object(uut, "handle_message") as mock_handle:
            uut.on_message(mock_mqtt_client, None, msg)
            mock_handle.assert_not_called()


def test_safe_json_decode_valid() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    result = uut.safe_json_decode('{"key": "value", "num": 42}')
    assert result == {"key": "value", "num": 42}


def test_safe_json_decode_bytes() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    result = uut.safe_json_decode(b'{"key": "value"}')
    assert result == {"key": "value"}


def test_safe_json_decode_none() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    result = uut.safe_json_decode(None)
    assert result == {}


def test_safe_json_decode_invalid() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    result = uut.safe_json_decode("not valid json")
    assert result == {}


def test_topic_generation(mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "mynode"

    uut = MqttPublisher(config, node_config, hass_config)
    discovery = Discovery(mock_provider, "mycontainer", "session123", "mynode")

    assert uut.config_topic(discovery) == "homeassistant/update/mynode_unit_test_mycontainer/update/config"
    assert uut.state_topic(discovery) == "updates2mqtt/mynode/unit_test/mycontainer/state"
    assert uut.general_topic(discovery) == "updates2mqtt/mynode/unit_test/mycontainer"
    assert uut.command_topic(mock_provider) == "updates2mqtt/mynode/unit_test"


def test_publish_hass_state(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "statenode"

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        discovery = Discovery(
            mock_provider,
            "testpkg",
            "sess001",
            "statenode",
            current_version="1.0",
            latest_version="2.0",
        )

        uut.publish_hass_state(discovery, in_progress=True)

        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "updates2mqtt/statenode/unit_test/testpkg/state"
        payload = json.loads(call_args[1]["payload"])
        assert payload["in_progress"] is True


def test_publish_hass_config(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "confignode"

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        discovery = Discovery(
            mock_provider,
            "mypkg",
            "sess002",
            "confignode",
            current_version="1.0",
            latest_version="2.0",
        )

        uut.publish_hass_config(discovery)

        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "homeassistant/update/confignode_unit_test_mypkg/update/config"


def test_loop_once(mock_mqtt_client: Mock) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        uut.loop_once()

        mock_mqtt_client.loop.assert_called_once()


def test_loop_once_no_client() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    # Should not raise when client is None
    uut.loop_once()


def test_start_connection_failure() -> None:
    config = OmegaConf.structured(MqttConfig)
    config.host = "invalid.host.example"
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    with pytest.raises(OSError, match="Connection Failure"):
        uut.start()


def test_subscribe_skips_duplicate(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    with (
        patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client),
        patch("asyncio.get_event_loop"),
    ):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        # First subscription
        topic1 = uut.subscribe_hass_command(mock_provider)
        call_count_after_first = mock_mqtt_client.subscribe.call_count

        # Second subscription should be skipped
        topic2 = uut.subscribe_hass_command(mock_provider)

        assert topic1 == topic2
        assert mock_mqtt_client.subscribe.call_count == call_count_after_first


def test_publish_no_client() -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)

    uut = MqttPublisher(config, node_config, hass_config)

    # Should not raise when client is None
    uut.publish("test/topic", {"key": "value"})


@pytest.mark.asyncio
async def test_execute_command_invalid_payload(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "testnode"

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start(event_loop=asyncio.get_running_loop())
        uut.subscribe_hass_command(mock_provider)

        # Message without proper pipe-separated format
        msg = MQTTMessage(topic=b"updates2mqtt/testnode/unit_test")
        msg.payload = b"invalid_payload_no_pipes"

        await uut.execute_command(msg, Mock(), Mock())

        # Should not call provider.command with invalid payload
        mock_provider.command.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_execute_command_wrong_source_type(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "testnode"

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start(event_loop=asyncio.get_running_loop())
        uut.subscribe_hass_command(mock_provider)

        # Message with wrong source type
        msg = MQTTMessage(topic=b"updates2mqtt/testnode/unit_test")
        msg.payload = b"wrong_source|comp|install"

        await uut.execute_command(msg, Mock(), Mock())

        mock_provider.command.assert_not_called()  # type: ignore[attr-defined]


# === clean_topics Tests ===


@pytest.mark.asyncio
async def test_clean_topics_exits_on_fatal_failure(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics should return immediately if fatal_failure is set"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.fatal_failure.set()

        # Should return immediately without creating a cleaner client
        with patch("updates2mqtt.mqtt.mqtt.Client") as mock_cleaner_class:
            await uut.clean_topics(mock_provider, wait_time=1)
            mock_cleaner_class.assert_not_called()


@pytest.mark.asyncio
async def test_clean_topics_removes_stale_discovery(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics should remove messages with different session"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    mock_cleaner = Mock()
    mock_cleaner.loop = Mock()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.providers_by_type[mock_provider.source_type] = mock_provider

        with patch("updates2mqtt.mqtt.mqtt.Client", return_value=mock_cleaner):
            # Simulate a message with old session arriving
            async def trigger_cleanup() -> None:
                await asyncio.sleep(0.1)
                # Get the on_message callback that was set
                on_message_callback = mock_cleaner.on_message
                # Create a mock retained message with old session
                msg = Mock()
                msg.retain = True
                msg.payload = {}
                msg.topic = f"homeassistant/update/cleannode_{mock_provider.source_type}_container1/update/config"
                on_message_callback(mock_cleaner, None, msg)

            # Run clean_topics with short wait_time
            task = asyncio.create_task(trigger_cleanup())
            await uut.clean_topics(mock_provider, wait_time=1)
            await task

            # Should have published empty message to remove stale topic
            calls = [call for call in mock_cleaner.publish.call_args_list if call[0][1] == ""]
            assert len(calls) == 1


@pytest.mark.asyncio
async def test_clean_topics_retains_current_discoveries(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics should keep messages with current session"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    mock_cleaner = Mock()
    mock_cleaner.loop = Mock()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.providers_by_type[mock_provider.source_type] = mock_provider
        with patch("updates2mqtt.mqtt.mqtt.Client", return_value=mock_cleaner):

            async def trigger_cleanup() -> None:
                await asyncio.sleep(0.1)
                on_message_callback = mock_cleaner.on_message
                msg = Mock()
                msg.retain = True
                msg.payload = {}
                msg.topic = f"homeassistant/update/cleannode_{mock_provider.source_type}_fooey/update/config"
                on_message_callback(mock_cleaner, None, msg)

            task = asyncio.create_task(trigger_cleanup())
            await uut.clean_topics(mock_provider, wait_time=1)
            await task

            # Should NOT have published empty message (message retained)
            empty_publish_calls = [call for call in mock_cleaner.publish.call_args_list if call[0][1] == ""]
            assert len(empty_publish_calls) == 0


@pytest.mark.asyncio
async def test_clean_topics_force_removes_untrackable(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics with force=True should remove messages without session"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    mock_cleaner = Mock()
    mock_cleaner.loop = Mock()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()
        uut.providers_by_type[mock_provider.source_type] = mock_provider

        with patch("updates2mqtt.mqtt.mqtt.Client", return_value=mock_cleaner):

            async def trigger_cleanup() -> None:
                await asyncio.sleep(0.1)
                on_message_callback = mock_cleaner.on_message
                msg = Mock()
                msg.retain = True
                msg.payload = {}
                msg.topic = f"homeassistant/update/cleannode_{mock_provider.source_type}_container1/update/config"
                on_message_callback(mock_cleaner, None, msg)

            task = asyncio.create_task(trigger_cleanup())
            await uut.clean_topics(mock_provider)
            await task

            # Should have published empty message to remove untrackable topic
            empty_publish_calls = [call for call in mock_cleaner.publish.call_args_list if call[0][1] == ""]
            assert len(empty_publish_calls) == 1


@pytest.mark.asyncio
async def test_clean_topics_skips_unrelated_topics(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics should skip topics that don't match prefixes"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    mock_cleaner = Mock()
    mock_cleaner.loop = Mock()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        with patch("updates2mqtt.mqtt.mqtt.Client", return_value=mock_cleaner):

            async def trigger_cleanup() -> None:
                await asyncio.sleep(0.1)
                on_message_callback = mock_cleaner.on_message
                msg = Mock()
                msg.retain = True
                # Topic doesn't match the expected prefixes
                msg.topic = "some/other/topic"
                msg.payload = json.dumps({"source_session": "old_session"}).encode()
                on_message_callback(mock_cleaner, None, msg)

            task = asyncio.create_task(trigger_cleanup())
            await uut.clean_topics(mock_provider, wait_time=1)
            await task

            # Should NOT have published anything (topic doesn't match)
            assert mock_cleaner.publish.call_count == 0


@pytest.mark.asyncio
async def test_clean_topics_subscribes_to_correct_topics(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    """clean_topics should subscribe to hass discovery and updates2mqtt topics"""
    config = OmegaConf.structured(MqttConfig)
    hass_config = OmegaConf.structured(HomeAssistantConfig)
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "cleannode"

    mock_cleaner = Mock()
    mock_cleaner.loop = Mock()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttPublisher(config, node_config, hass_config)
        uut.start()

        with patch("updates2mqtt.mqtt.mqtt.Client", return_value=mock_cleaner):
            await uut.clean_topics(mock_provider, wait_time=0)

            # Should subscribe to both topic patterns
            subscribe_calls = mock_cleaner.subscribe.call_args_list
            topics_subscribed = [call[0][0] for call in subscribe_calls]

            assert "homeassistant/update/#" in topics_subscribed
            assert f"updates2mqtt/cleannode/{mock_provider.source_type}/#" in topics_subscribed
