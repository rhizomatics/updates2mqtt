# Without a Configuration File

The core configuration can be supplied by environment variables and container labels, everything else will default, either to fixed values built into Updates2MQTT, or in the case of the node name, taken from the operating system.

| Env Var              | Default      |
| -------------------- | ------------ |
| MQTT_HOST            | localhost    |
| MQTT_PORT            | 1883         |
| MQTT_USER            | *NO DEFAULT* |
| MQTT_PASS            | *NO DEFAULT* |
| MQTT_VERSION         | 3.11         |
| U2M_LOG_LEVEL        | INFO         |
| U2M_REMOVE_OLD_IMAGE | false        |
| PORTAINER_URL        | *NONE*       |
| PORTAINER_API_KEY    | *NONE*       |
| PORTAINER_CA_CERTS   | *NONE*       |
| PORTAINER_VERIFY_SSL | true         |

Startup will fail if `MQTT_USER` and `MQTT_PASS` are not defined some how. Run `u2m-cli mqtt=check` inside the container to see which settings are picked up from the environment, see [Troubleshooting](https://updates2mqtt.rhizomatics.org.uk/help/troubleshooting/#checking-mqtt-and-update-settings).

The `PORTAINER_` env vars are only needed to update containers in Portainer stacks, see [Portainer](https://updates2mqtt.rhizomatics.org.uk/installation/#on-portainer).

The example [docker-compose.yaml](https://updates2mqtt.rhizomatics.org.uk/configuration/examples/docker_compose/index.md) and [.env](https://updates2mqtt.rhizomatics.org.uk/configuration/examples/env/index.md) demonstrate one way of doing this, or skip the `.env` file and use an `environment` section in the Compose file.

Set `U2M_AUTOGEN_CONFIG=0` in the environment to prevent a default config file being created in the local compose directory if you want to keep it zero-configuration-file.
