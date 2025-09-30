[![Rhizomatics Open Source](https://avatars.githubusercontent.com/u/162821163?s=96&v=4)](https://github.com/rhizomatics)

# updates2mqtt

## Summary

Use Home Assistant to notify you of updates to Docker images for your containers and optionally perform the *pull* (or optionally *build*) and *update*.

![Example Home Assistant settings page](images/hass_update_page.png "Home Assistant Updates")

## Description

updates2mqtt perioidically checks for new versions of components being available, and publishes new version info to MQTT.
HomeAssistant auto discovery is supported, so all updates can be seen in the same place as Home Assistant's
own components and add-ins.

Currently only Docker containers are supported, either via an image registry check, or a git repo for source. The design is modular, so other update sources can be added, at least for notification. The next anticipated is **apt** for Debian based systems.

Components can also be updated, either automatically or triggered via MQTT, for example by hitting the *Install*
button in the HomeAssistant update dialog. Icons and release notes can be specified for a better HA experience.

## Install

updates2mqtt prefers to be run inside a Docker container.

### Manual
```
uv sync
uv run updates2mqtt
```
### Docker

See ``examples`` directory for a working ``docker-compose.yaml`` which presumes that ``updates2mqtt`` has been checked out inside a ``build`` subdirectory of the docker-compose directory.

## Configuration

Create file `config.yaml` in `conf` directory. If the file is not present, a default file will be generated.

### Example configuration file

```yaml

node:
  name: docker-host-1
mqtt:
  host: localhost
  user: mymqttuser
  password: mymqttsecretpassword
  port: 1883
  topic_root: updates2mqtt
homeassistant:
  discovery:
    prefix: homeassistant
    enabled: true
  state_topic_suffix: state
docker:
  enabled: true
  default: true
  allow_pull: true # if true, will do a `docker pull` if an update is available
  allow_restart: true # if true, will do a `docker-compose restart` if an update is installed
  allow_build: true # if true, will do a `docker-compose build` if a git repo is configured
  compose_version: v2 # Controls whether to use `docker-compose` (v1) or `docker compose` (v2) command
  default_entity_picture_url: https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png
  device_icon: mdi:train-car-container
scan_interval: 10800 # sleep interval between scan runs, in seconds
log:
  level: INFO
```

### Moving Secrets Out of Config

Example use of environment variables, e.g. for secrets:

```
mqtt:
    password: ${oc.env:MQTT_PASS}
```
### Customizing images and release notes

Individual docker containers can have customized entity pictures or release notes, using env variables, for example in the `docker-compose.yaml` or in a separate `.env` file:

```
    environment:
      - UPD2MQTT_PICTURE=https://frigate.video/images/logo.svg
      - UPD2MQTT_RELNOTES=https://github.com/blakeblackshear/frigate/releases
```

The images will show up in the *Update* section of *Settings* menu in HomeAssistant,
as will the release notes link. SVG icons should be used.

Some popular services have the icon and release note links pre-configured, in `common_packages.yaml`,
and packages from `linuxserver.io` can have metadata automatically discovered.

#### Icon Sources

- [Homarr Dashboard Icons](https://github.com/homarr-labs/dashboard-icons)
- [Self Hosted Icons](https://github.com/selfhst/icons)
- [Simple Icons](https://github.com/simple-icons/simple-icons)
- [Tabler Icons](https://tabler.io/icons)
- [Papirus Icons](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
- [Homelab SVG Assets](https://github.com/loganmarchione/homelab-svg-assets)

### Automated updates

If Docker containers should be immediately updated, without any confirmation
or trigger, *e.g.* from the HomeAssistant update dialog, then set an environment variable `UPD2MQTT_UPDATE`
in the target container to `Auto` ( it defaults to `Passive`)

### Custom docker builds

If the image is locally built from a checked out git repo, package update can be driven
by the availability of git repo changes to pull rather than a new image on a Docker registry.

Declare the git path using the env var in ``UPD2MQTT_GIT_REPO_PATH`` in the docker container ( directly or via an ``.env`` file).
The git repo at this path will be used as the source of timestamps, and an update command will carry out a 
``git pull`` and ``docker-compose build`` rather than pulling an image.

Note that the updates2mqtt docker container needs access to this path declared in its volumes, and that has to
be read/write if automated install required.

### Environment Variables

The following environment variables can be used to configure updates2mqtt:

| Env Var | Description | Default  |
|---------| ------------|----------|
| `UPD2MQTT_UPDATE`  | Update mode, either `Passive` or `Auto`. If `Auto`, updates will be installed automatically. | `Passive` |
| `UPD2MQTT_PICTURE`  | URL to an icon to use in Home Assistant.  | Docker logo URL   |
| `UPD2MQTT_RELNOTES` | URL to release notes for the package.  |  | 
| `UPD2MQTT_GIT_REPO_PATH` | Relative path to a local git repo if the image is built locally.  | |


## Release Support

| Ecosystem | Support     | Comments                                                                                           |
|-----------|-------------|----------------------------------------------------------------------------------------------------|
| Docker    | Scan. Fetch | Fetch is ``docker pull`` only. Restart support only for ``docker-compose`` image based containers. |
  
  
## HomeAssistant integration

Any updates that have support for automated install will automatically show in the
Home Assistant settings page.

If the package supports automated update, then *Skip* and *Install* buttons will appear on the Home Assistant
interface, and the package can be remotely fetched and the component restarted.

## Development
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![CodeQL](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates)