# Without a Configuration File

The core configuration can be supplied by environment variables and container labels, everything else will default, either to fixed values built into Updates2MQTT, or in the case of the node name, taken from the operating system.

| Env Var       | Default      |
|---------------|--------------|
| MQTT_HOST     | localhost    |
| MQTT_PORT     | 1883         |
| MQTT_USER     | *NO DEFAULT* |
| MQTT_PASSWORD | *NO DEFAULT* |
| MQTT_VERSION  | 3.11.        |
| U2M_LOG_LEVEL | INFO         |

Startup will fail if `MQTT_USER` and `MQTT_PASSWORD` are not defined some how.

The example [docker-compose.yaml](examples/docker_compose.md) and [.env](examples/env.md) demonstrate one way of doing this, or skip the `.env` file and use an `environment` section in the Compose file.

Set `U2M_AUTOGEN_CONFIG=0` in the environment to prevent a default config file being created in the local compose directory if you want to keep it zero-configuration-file.
