# Minimal Configuration

The core configuration can be supplied by environment variables, everything else will default, either to fixed values built into Updates2MQTT, or in the case of the node name, taken from the operating system.

| Env Var       | Default      |
|---------------|--------------|
| MQTT_HOST     | localhost    |
| MQTT_PORT     | 1883         |
| MQTT_USER     | *NO DEFAULT* |
| MQTT_PASSWORD | *NO DEFAULT* |
| MQTT_VERSION  | 3.11.        |
| U2M_LOG_LEVEL | INFO         |

Startup will fail if `MQTT_USER` and `MQTT_PASSWORD` are not defined some how.

The example [docker-compose.yaml](docker_compose.md) and [.env](env.md) demonstrate one way of doing this, or skip
the `.env` file and use an `environment` section in the Compose file.

# Configuration File

The configuration file is optional, and only needed if you have to override the defaults.

Create file `config.yaml` in `conf` directory. If the file is not present, a default file will be generated, and the parent director if necessary. If you don't want that to happen, then set `U2M_AUTOGEN_CONFIG=0`.

### Example configuration file

This is a maximal config file, the minimum is no config file at all, which will generate a default config file. The only mandatory values are the MQTT user name and password, everything else can be omitted ( although
its best to have at least a `node` `name` value so HomeAssistant doesn't show some ugly generated Docker host name).

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
  protocol: 3.11 # Can be changed to 5 if your broker supports it
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

## Improving Security

### Moving Secrets Out of Config

Example use of environment variables, e.g. for secrets:

```
mqtt:
    password: ${oc.env:MQTT_PASS}
```

### Running as non-root

It is good practice not to run Docker containers as root, and `updates2mqtt` will
work with any user so long as it has Docker permissions, usually as a result
of being a member of the `docker` group.

To create a suitable use, use the shell command below - it will create a user
that can only be used for this purpose, and can't otherwise login. It assumes there is already a group called `docker` with access to the Docker Daemon, if you dont
have one, follow the [Docker Post Install Steps](https://docs.docker.com/engine/install/linux-postinstall/) which explain how and why to do it.

```bash
sudo adduser --system --ingroup docker --no-create-home -shell /sbin/nologin updates2mqtt
```

Note the `uid` that is reported here. If you don't know the `gid` for the `docker` group, use `grep docker /etc/group`. In this example, our `uid` is `130` and the `gid` of `docker` group is `119`.

In the `docker-compose.yaml`, set the user and group using [user](https://docs.docker.com/reference/compose-file/services/#user) attribute:

```yaml
services:
  updates2mqtt:
    container_name: updates2mqtt
    image: ghcr.io/rhizomatics/updates2mqtt:release
    user: 130:119
```

If you're using Updates2MQTT to update local git repos, then the user created above will also need `rw` access to those, which you can do by making it a member of the
same group as owns the repos and making sure they have group `rw` access configured.

For more information, see the [Understanding the Docker USER Instruction](https://www.docker.com/blog/understanding-the-docker-user-instruction/) article from Docker.

### MQTT Access Control

Its best to have a dedicated MQTT user for Updates2MQTT, for security and debug. For most
secure installations, only use secure ports with validated certificates, although this will
require more complicated setup and ongoing support, including using host names rather than
IP addresses, and with [LetsEncrypt](https://letsencrypt.org) to update certificates.

The two brokers most commonly used with Home Assistant, **Mosquitto** and **EMQX**, both have
access control mechanisms, so you can restrict the user account for Updates2MQTT to only be able
to read and write its own topics.

## Customizing images and release notes

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

