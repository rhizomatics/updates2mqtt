# Using A Configuration File

The configuration file is optional, and only needed if you have to override the defaults. See [Without a Config File](zero_config_file.md) for the alternatives.

Create file `config.yaml` in `conf` directory. If the file is not present, a default file will be generated, and the parent director if necessary. If you don't want that to happen, then set `U2M_AUTOGEN_CONFIG=0`.

## Example configuration file

This is a maximal config file, the minimum is no config file at all, which will generate a default config file. The only mandatory values are the MQTT user name and password, everything else can be omitted ( although
its best to have at least a `node` `name` value so HomeAssistant doesn't show some ugly generated Docker host name).

```yaml title="config.yaml snippet"

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
  device_creation: true # create a Home Assistant device and associate it with each update entity
  area: "Server Room" # suggest an area for Home Assistant to give to the Device
  extra_attributes: true # use `json_attributes_topic` feature in Home Assistant to source state attributes from discover
  force_command_creation: # create a command topic even if there's no support for automated update
docker:
  enabled: true
  allow_pull: true # if true, will do a `docker pull` if an update is available
  allow_restart: true # if true, will do a `docker-compose up` if an update is installed
  allow_build: true # if true, will do a `docker-compose build` if a git repo is configured
  compose_version: v2 # Controls whether to use `docker-compose` (v1) or `docker compose` (v2) command
  default_entity_picture_url: https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png # Picture for update dialog
  device_icon: mdi:docker # Material Design Icon to use when browsing entities in Home Assistant
  default_api_backoff: 600 # Default time to back off container registry APIs
  # device_icon: mdi:train-car-container # Alternative icon if you don't like Docker branding
  discover_metadata:
    linuxserver.io:
      enabled: true
      cache_ttl: 604800 # cache metadata for 1 week
  image_ref_select: # limit the containers which will be published to Home Assistant
    include:
    - .*special-dev
    exclude:
    - .*dev
    - .*nightly
  version_select:  # limit the containers which will be published to Home Assistant
     exclude:
     -  .*-beta.*
     include: 
     - 1\..*
scan_interval: 10800 # sleep interval between scan runs, in seconds
log:
  level: INFO
```


