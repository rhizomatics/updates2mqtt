This page available in [English](https://updates2mqtt.rhizomatics.org.uk/index.md), [Deutsch](https://updates2mqtt.rhizomatics.org.uk/de/index.md), [Español](https://updates2mqtt.rhizomatics.org.uk/es/index.md), [Français](https://updates2mqtt.rhizomatics.org.uk/fr/index.md), [हिन्दी](https://updates2mqtt.rhizomatics.org.uk/hi/index.md), [Italiano](https://updates2mqtt.rhizomatics.org.uk/it/index.md),[日本語](https://updates2mqtt.rhizomatics.org.uk/ja/index.md), [Nederlands](https://updates2mqtt.rhizomatics.org.uk/nl/index.md), [Polski](https://updates2mqtt.rhizomatics.org.uk/pl/index.md), [Português](https://updates2mqtt.rhizomatics.org.uk/pt/index.md), [中文（简体)](https://updates2mqtt.rhizomatics.org.uk/zh-Hans/index.md)

# updates2mqtt

## Summary

Let Home Assistant tell you about new updates to Docker images for your containers.

Read the release notes, and optionally click *Update* to trigger a Docker *pull* (or optionally *build*) and *update*.

## Description

Updates2MQTT perioidically checks for new versions of components being available, and publishes new version info to MQTT. HomeAssistant auto discovery is supported, so all updates can be seen in the same place as Home Assistant’s own components and add-ins.

Currently only Docker containers are supported, either via an image registry check (using either v1 Docker APIs or the OCI v2 API), or a git repo for source (see [Local Builds](https://updates2mqtt.rhizomatics.org.uk/local_builds/index.md)), with specific handling for Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay and LinuxServer Registry, with adaptive behaviour to cope with most others. The design is modular, so other update sources can be added, at least for notification. **Portainer** stacks are supported for container rebuild/restart as well as Docker Compose, see [Portainer](https://updates2mqtt.rhizomatics.org.uk/configuration/portainer/index.md). Support for **apt** on Debian based systems may follow.

Components can also be updated, either automatically or triggered via MQTT, for example by hitting the *Install* button in the HomeAssistant update dialog. Icons and release notes can be specified for a better HA experience. See [Home Assistant Integration](https://updates2mqtt.rhizomatics.org.uk/home_assistant/index.md) for details.

To get started, read the [Installation](https://updates2mqtt.rhizomatics.org.uk/installation/index.md) and [Configuration](https://updates2mqtt.rhizomatics.org.uk/configuration/index.md) pages.

AI agents can use the [documentation index](https://updates2mqtt.rhizomatics.org.uk/llms.txt) to find relevant pages, or fetch the [complete Markdown documentation](https://updates2mqtt.rhizomatics.org.uk/llms-full.txt).

For a quick spin, try this:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

or without Docker, using [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

It also comes with a basic command line tool that will perform the analysis for a single running container, or fetch manifests, JSON blobs and lists of tags from remote registries (known to work with GitHub, GitLab, Codeberg, Quay, LSCR and Microsoft MCR).

## Release Support

Presently only Docker containers are supported, although others are planned, probably with priority for `apt`.

| Ecosystem | Support     | Comments                                                                                                                                                                                                                            |
| --------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Docker    | Scan. Fetch | Fetch is `docker pull`, or `git pull` and `docker compose build` for local builds. Restart support for `docker compose` and [Portainer](https://updates2mqtt.rhizomatics.org.uk/configuration/portainer/index.md) stack containers. |

Once a container has been recreated with its new image, the old image can optionally be removed, to save disk space, by setting `remove_old_image: true` in the `docker` section of the config file, or the `U2M_REMOVE_OLD_IMAGE=true` env var. Images still used by another container, running or stopped, are left alone.

## Heartbeat

A heartbeat JSON payload is optionally published periodically to a configurable MQTT topic, defaulting to `healthcheck/{node_name}/updates2mqtt`. It contains the current version of Updates2MQTT, the node name, a timestamp, and some basic stats.

## Healthcheck

A `healthcheck.sh` script is included in the Docker image, and can be used as a Docker healthcheck, if the container environment variables are set for `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` and `MQTT_PASS`. It uses the `mosquitto-clients` Linux package which provides `mosquitto_sub` command to subscribe to topics.

Tip

Check healthcheck is working using `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (can omit `| jq` if you don’t have jsonquery installed, but much easier to read with it)

Another approach is using a restarter service directly in Docker Compose to force a restart, in this case once a day:

Example Compose Service

```yaml
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Target Containers

While `updates2mqtt` will discover and monitor all containers running under the Docker daemon, there are some options to make to those containers to tune how it works.

These happen by adding environment variables or docker labels to the containers, typically inside an `.env` file, or as `environment` options inside `docker-compose.yaml`.

### Automated updates

If Docker containers should be immediately updated, without any confirmation or trigger, *e.g.* from the HomeAssistant update dialog, then set an environment variable `UPD2MQTT_UPDATE` in the target container to `Auto` ( it defaults to `Passive`). If you want it to update without publishing to MQTT and being visible to Home Assistant, then use `Silent`.

Example Compose Snippet

```yaml
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Automated updates can also apply to local builds, where a `git_repo_path` has been defined - if there are remote commits available to pull, then a `git pull`, `docker compose build` and `docker compose up` will be executed.

## Related Projects

Other apps useful for self-hosting with the help of MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Report system health and metrics via MQTT

Find more at [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

For a more powerful Docker focussed update manager, try [What’s Up Docker](https://getwud.github.io/wud/)

## Development

This component relies on several open source packages:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK for Python for access to Docker APIs
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTT client
- [OmegaConf](https://omegaconf.readthedocs.io) for configuration and validation
- [structlog](https://www.structlog.org/en/stable/) for structured logging (optionally JSON) and [rich](https://rich.readthedocs.io/en/stable/) for better exception reporting
- [hishel](https://hishel.com/) for caching metadata
- [httpx](https://www.python-httpx.org) for retrieving metadata
- The Astral [uv](https://docs.astral.sh/uv/) and [ruff](https://docs.astral.sh/ruff/) tools for development and build
- [pytest](https://docs.pytest.org/en/stable/) and supporting add-ins for automated testing
- [usingversion](https://pypi.org/project/usingversion/) to log current version info

## Rhizomatics Open Source for Home Assistant

### HACS

- [Appliance AutoNotify](https://appliance-autonotify.rhizomatics.org.uk) - Live activities on your phone for dishwashers, robot vacuums, power monitors etc with no config, no YAML, no blueprints, no automations.
- [Auto Arm](https://autoarm.rhizomatics.org.uk) - Automatically arm and disarm Home Assistant alarm control panels using physical buttons, presence, calendars, sun and more. Integrates with Frigate profiles.
- [Camera AutoNotify](https://camera-autonotify.rhizomatics.org.uk) - Instant notifications for Frigate (and other camera systems coming) with no config, no blueprints, no YAML, no automations.
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) and Syslog event capture for Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Unified notification for easy multi-channel messaging, including powerful chime and security camera integration.

### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integrate with ANPR/ALPR licence plate cameras via file system (NAS/FTP) to MQTT with optional image analysis and UK DVLA integration.
- [HomeAssistant REPL](https://homeassistant-repl.rhizomatics.org.uk) - Python REPL for Home Assistant development and data exploration.
