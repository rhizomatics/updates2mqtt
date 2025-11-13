[![Rhizomatics Open Source](https://avatars.githubusercontent.com/u/162821163?s=96&v=4)](https://github.com/rhizomatics)

# updates2mqtt

![PyPI - Version](https://img.shields.io/pypi/v/updates2mqtt)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/supernotify)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/updates2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/updates2mqtt/main)
[![Publish Python 🐍 distribution 📦 to PyPI and TestPyPI](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml)
[![Github Deploy](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml)
[![CodeQL](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates)

## Summary

Use Home Assistant to notify you of updates to Docker images for your containers and optionally perform the *pull* (or optionally *build*) and *update*.

![Example Home Assistant update dialog](images/ha_update_detail.png "Home Assistant Updates")

## Description

updates2mqtt perioidically checks for new versions of components being available, and publishes new version info to MQTT. HomeAssistant auto discovery is supported, so all updates can be seen in the same place as Home Assistant's own components and add-ins.

Currently only Docker containers are supported, either via an image registry check, or a git repo for source (see [Local Builds](local_builds.md)). The design is modular, so other update sources can be added, at least for notification. The next anticipated is **apt** for Debian based systems.

Components can also be updated, either automatically or triggered via MQTT, for example by hitting the *Install* button in the HomeAssistant update dialog. Icons and release notes can be specified for a better HA experience.

To get started, read the [Installation](installation.md) and [Configuration](configuration.md) pages.

For a quick spin, try this:

```yaml
docker run -e MQTT_USER=user1 -e MQTT_PASS=pass1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:release
```

## Release Support

Presently only Docker containers are supported, although others are planned,
probably with priority for `apt`.

| Ecosystem | Support     | Comments                                                                                           |
|-----------|-------------|----------------------------------------------------------------------------------------------------|
| Docker    | Scan. Fetch | Fetch is ``docker pull`` only. Restart support only for ``docker-compose`` image based containers. |
  
## Healthcheck

A heartbeat JSON payload is optionally published periodically to a configurable MQTT topic, defaulting to `healthcheck/{node_name}/updates2mqtt`. It contains the current version of updates2mqtt, the node name, a timestamp, and some basic stats.

A `healthcheck.sh` script is included in the Docker image, and can be used as a Docker healthcheck, if the container environment variables are set for `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` and `MQTT_PASS`.

TIP: Check healthcheck is working using `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq`
  
## HomeAssistant integration

Any updates that have support for automated install will automatically show in the
Home Assistant settings page if the [MQTT Integration](https://www.home-assistant.io/integrations/mqtt/) is installed and automatic discovery is not disabled.

![Home Assistant MQTT Integraion configuration](images/ha_mqtt_discovery.png "Home Assistant MQTT Discovery")

The `homeassistant` default topic prefix matches the default updates2mqtt config, if its changed in HomeAssistant, then the updates2mqtt config must be changed to match.

![Home Assistant updates in Settings](images/ha_update_page.png "Home Assistant Updates")

For Home Assistant integration, updates2mqtt represents each component being managed as a [MQTT Update](https://www.home-assistant.io/integrations/update.mqtt/) entity, and uses [MQTT discovery(https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery)] so that HomeAssistant automatically picks up components discovered by updates2mqtt with zero configuration on HomeAssistant itself. 

There are 3 separate types of MQTT topic used for HomeAssisstant integration:

- *Config* to support auto discovery. A topic is created per component, with a name like `homeassistant/update/dockernuc_docker_jellyfin/update/config`. This can be disabled in the config file, and the `homeassistant` topic prefix can also be configured.
- *State* to report the current version and the latest version available, again one topic per component, like `updates2mqtt/dockernuc/docker/jellyfin`.
- *Command* to support triggering an update. These will be created on the fly by HomeAssistant when an update is requested, and updates2mqtt subscribes to pick up the changes, so you won't typically see these if browsing MQTT topics. Only one is needed per updates2mqtt agent, with a name like `updates2mqtt/dockernuc/docker`

If the package supports automated update, then *Skip* and *Install* buttons will appear on the Home Assistant
interface, and the package can be remotely fetched and the component restarted.

## Related Projects

Other apps useful for self-hosting with the help of MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Report system health and metrics via MQTT

## Development

Access to Docker APIs uses the Python [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK for Python. [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) is used for MQTT access, and [OmegaConf](https://omegaconf.readthedocs.io) for configuration.
