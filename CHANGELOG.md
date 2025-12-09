# CHANGELOG

## 1.5.1
- `MQTT_VERSION` environment variable added, defaults to `3.11`
- `U2M_AUTOGEN_CONFIG` environment variable added to control auto-generation of config files and directories
- `U2M_LOG_LEVEL` environment variable added to set log level without config file
- Title generation for Docker images reverts to same whether HA device set or not
- Test added to ensure component always functions without a config file, if no env var present
## 1.5.0
- Target specific service on docker compose commands, where available from `com.docker.compose.service` label
- Log level in config is now an enum, and forced to be upper case
- Removed unnecessary latest_version fields from config message, which also saves a redundant MQTT subscription
- Publication of `command_topic` for each discovery can now be forced with `force_command_topic` option
- More common packages: docker:cli
- Common packages can now match on the image ref rather than base name, for example `docker:cli`
- Reduced log noise in INFO and increased logging detail for DEBUG
- Common Packages now allow entries without all the values, initially `rtl_433` which lacks a logo
## 1.4.2
- Replace `origin` in config MQTT message with `device` for better HomeAssistant compatibility
- An `area` can be defined in the Home Assistant section of config and this will then be used as `suggested_area` for device
- Icon and release note info added for Owntone, Nextcloud, n8n, and Homarr
- More testcases
## 1.4.1
- More logging for Docker discovery on why Home Assistant doesn't show an update button
- More test cases
- `MqttClient` is now `MqttPublisher` to avoid confusion with actual MQTT client
- Task cleanup now only interrupts explicit list of tasks - healthcheck and discovery tasks
## 1.4.0
- MQTT protocol can now be set, to one of `3.1`,`3.11` or `5`
- Debug messages now provided for `on_subscribe` and `on_unsubscribe` callbacks
- Troubleshooting, installation, configuration docs updated, images optimized

## 1.3.7
- Improved initial setup when run without config or env vars for MQTT
- Minor test deps update and pyproject docs

## 1.3.6
- Changed exit code on graceful shutdown to 143
- App now exits if the MQTT username / password is not authorized
- Improved handling of env vars, default config now assumes MQTT_HOST etc unless overridden
  - Will now run without a config if correct `MQTT_HOST`,`MQTT_USER`,`MQTT_PASS`,`MQTT_PORT` env vars set or match the defaults (`127.0.0.1:1883`)
- Deps update