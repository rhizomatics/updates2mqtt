# Configuration

Create file `config.yaml` in `conf` directory. If the file is not present, a default file will be generated.

### Example configuration file

This is a maximal config file, the minimum is no config file at all, which will generate a default config file. The only mandatory values are the MQTT user name and password, everything else can be omitted.

```yaml

node:
  name: docker-host-1 # Unique name for this instance, used to name MQTT entities. Defaults to O/S hostname
  git_repo_path: /usr/bin/git # Path to git inside container, needed only if non-default and using local docker builds
  healthcheck:
    enabled: true
    interval: 300 # publish a heartbeat every 5 minutes
    topic_template: healthcheck/{node_name}/updates2mqtt
mqtt:
  host: ${oc.env:MQTT_HOST}
  user: ${oc.env:MQTT_USER}
  password: ${oc.env:MQTT_PASS}$ # Use an environment variable for secrets
  port: ${oc.env:MQTT_PORT}
  topic_root: updates2mqtt
homeassistant:
  discovery:
    prefix: homeassistant # Matches the default MQTT discovery prefix in Home Assistant
    enabled: true
  state_topic_suffix: state
docker:
  enabled: true
  allow_pull: true # if true, will do a `docker pull` if an update is available
  allow_restart: true # if true, will do a `docker-compose up` if an update is installed
  allow_build: true # if true, will do a `docker-compose build` if a git repo is configured
  compose_version: v2 # Controls whether to use `docker-compose` (v1) or `docker compose` (v2) command
  default_entity_picture_url: https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png # Picture for update dialog
  device_icon: mdi:docker # Material Design Icon to use when browsing entities in Home Assistant
  # device_icon: mdi:train-car-container # Alternative icon if you don't like Docker branding
  discover_metadata:
    linuxserver.io:
      enabled: true
      cache_ttl: 604800 # cache metadata for 1 week
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

#### Icon Sources

Updates look nicer in Home Assistant with a suitable icon. Updates2mqtt comes
pre-packaged with some common ones, in `common_packages.yaml`, and can automatically fetch them (and release links) for the popular [linuxserver.io](https://www.linuxserver.io) packages.  

If you have something not covered, here are some good places to look for self-hosted app icons:

- [Homarr Dashboard Icons](https://github.com/homarr-labs/dashboard-icons)
- [Self Hosted Icons](https://github.com/selfhst/icons)
- [Simple Icons](https://github.com/simple-icons/simple-icons)
- [Tabler Icons](https://tabler.io/icons)
- [Papirus Icons](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
- [Homelab SVG Assets](https://github.com/loganmarchione/homelab-svg-assets)

### Automated updates

If Docker containers should be immediately updated, without any confirmation
or trigger, *e.g.* from the HomeAssistant update dialog, then set an environment variable `UPD2MQTT_UPDATE` in the target container to `Auto` ( it defaults to `Passive`)


### Environment Variables

The following environment variables can be used to configure updates2mqtt:

| Env Var | Description | Default  |
|---------| ------------|----------|
| `UPD2MQTT_UPDATE`  | Update mode, either `Passive` or `Auto`. If `Auto`, updates will be installed automatically. | `Passive` |
| `UPD2MQTT_PICTURE`  | URL to an icon to use in Home Assistant.  | Docker logo URL   |
| `UPD2MQTT_RELNOTES` | URL to release notes for the package.  |  | 
| `UPD2MQTT_GIT_REPO_PATH` | Relative path to a local git repo if the image is built locally.  | |
| `UPD2MQTT_IGNORE` | If set to `True`, the container will be ignored by updates2mqtt. | False |
