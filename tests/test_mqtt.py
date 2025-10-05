import asyncio
import json
import time
from unittest import mock
from unittest.mock import Mock, patch

import paho.mqtt.client
import pytest
from paho.mqtt.client import MQTTMessage

from updates2mqtt.config import HomeAssistantConfig, MqttConfig, NodeConfig
from updates2mqtt.model import Discovery, ReleaseProvider
from updates2mqtt.mqtt import MqttClient


def test_publish(mock_mqtt_client: Mock) -> None:
    config = MqttConfig()
    hass_config = HomeAssistantConfig()
    node_config = NodeConfig()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttClient(config, node_config, hass_config)
        uut.start()

        uut.publish("test.topic.123", {"foo": "a8", "bar": False})
        mock_mqtt_client.connect.assert_called_once()
        mock_mqtt_client.publish.assert_called_with("test.topic.123", payload='{"foo": "a8", "bar": false}', qos=0, retain=True)


@pytest.mark.asyncio
async def test_handler(mock_mqtt_client: Mock) -> None:
    config = MqttConfig()
    hass_config = HomeAssistantConfig()
    node_config = NodeConfig()
    node_config.name = "testing"
    with patch("updates2mqtt.mqtt.mqtt.Client", new=mock_mqtt_client):
        uut = MqttClient(config, node_config, hass_config)
        uut.start(event_loop=asyncio.get_running_loop())

        provider = Mock(spec=ReleaseProvider)
        provider.source_type = "unit_test"
        discovery = Discovery(provider, "qux", session="test-mqtt-123")
        provider.command.return_value = discovery
        provider.hass_state_format.return_value = {}

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
    config = MqttConfig()
    hass_config = HomeAssistantConfig()
    node_config = NodeConfig("TESTBED")

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttClient(config, node_config, hass_config)
        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)
        dummy_callable = lambda: None  # noqa: E731

        mqtt_bytes_msg = MQTTMessage(topic=b"updates2mqtt/TESTBED/unit_test")
        mqtt_bytes_msg.payload = b"unit_test|fooey|install"
        await uut.execute_command(mqtt_bytes_msg, dummy_callable, dummy_callable)

        mock_mqtt_client.publish.assert_called_with(
            "updates2mqtt/TESTBED/unit_test/fooey",
            payload=json.dumps(
                {
                    "installed_version": "v2",
                    "latest_version": "v2",
                    "title": "Update for fooey on TESTBED",
                    "in_progress": True,
                }
            ),
            qos=0,
            retain=True,
        )


@pytest.mark.asyncio
async def test_execute_command_local(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = MqttConfig()
    hass_config = HomeAssistantConfig()
    node_config = NodeConfig("TESTBED")

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttClient(config, node_config, hass_config)

        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)

        discovery = Discovery(mock_provider, "fooey", session="test-mqtt-123", current_version="v1")
        uut.local_message(discovery, "install")
        await asyncio.sleep(1)

        mock_mqtt_client.publish.assert_called_with(
            "updates2mqtt/TESTBED/unit_test/fooey",
            payload=json.dumps(
                {
                    "installed_version": "v2",
                    "latest_version": "v2",
                    "title": "Update for fooey on TESTBED",
                    "in_progress": True,
                }
            ),
            qos=0,
            retain=True,
        )


@pytest.mark.asyncio
async def test_stop(mock_mqtt_client: Mock, mock_provider: ReleaseProvider) -> None:
    config = MqttConfig()
    hass_config = HomeAssistantConfig()
    node_config = NodeConfig()

    with patch.object(paho.mqtt.client.Client, "__new__", lambda *_args, **_kwargs: mock_mqtt_client):
        uut = MqttClient(config, node_config, hass_config)

        uut.start(event_loop=asyncio.get_running_loop())

        uut.subscribe_hass_command(mock_provider)

        uut.stop()
        await asyncio.sleep(1)
        mock_mqtt_client.loop_stop.assert_called()
        mock_mqtt_client.disconnect.assert_called()
