# Configuration

## Without a Configuration File

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

The example [docker-compose.yaml](examples/docker_compose.md) and [.env](examples/env.md) demonstrate one way of doing this, or skip
the `.env` file and use an `environment` section in the Compose file.

Set `U2M_AUTOGEN_CONFIG=0` in the environment to prevent a default config file being created in the local compose directory if you want to keep it zero-configuration-file.

## With A Configuration File

The configuration file is optional, and only needed if you have to override the defaults.

Create file `config.yaml` in `conf` directory. If the file is not present, a default file will be generated, and the parent director if necessary. If you don't want that to happen, then set `U2M_AUTOGEN_CONFIG=0`.

### Example configuration file

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

## Improving Security

### Moving Secrets Out of Config

Example use of environment variables, e.g. for secrets:

```yaml title="config.yaml snippet"
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

```yaml title="docker compose snippet"
services:
  updates2mqtt:
    container_name: updates2mqtt
    image: ghcr.io/rhizomatics/updates2mqtt:latest
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

```yaml title="docker compose snippet"
    environment:
      - UPD2MQTT_PICTURE=https://frigate.video/images/logo.svg
      - UPD2MQTT_RELNOTES=https://github.com/blakeblackshear/frigate/releases
```

or using labels

```yaml title="docker compose snippet"
    labels:
      updates2mqtt.picture: https://frigate.video/images/logo.svg
      updates2mqtt.relnotes: https://github.com/blakeblackshear/frigate/releases
```
  l
The images will show up in the *Update* section of *Settings* menu in HomeAssistant,
as will the release notes link. SVG icons should be used.

## Customizing Versions

Updates2MQTT attempts to find the most human-friendly representation of image versions that
can be reliably used. Ideally that's a `v1.5.4` type version (whether formally SemVer or just traditional version).

By default, configurable using `version_policy` in the Docker section of the config, it uses an `auto` version policy that will choose the most meaningful, and fall back to digests where versions aren't available (usually via image labels/annotations). This will also take
into account where updates are throttled, or a pinned digest declared in the container.

This can be overridden at container level using using the `updates2mqtt.version_policy` container label or `UPD2MQTT_VERSION_POLICY` environment variable:

   - `AUTO` - to do the best it can with versions, git repo digests, index digests or config digests
   - `VERSION` - always choose simple version unless version not available
     - Some images use version oddly, where its more of a label applying to multiple releases than a version. Also
       there's guarantee for container images that a human friendly version always points to the same thing.
     - This is useful where you know the image has sensible versions and trust it enough
   - `DIGEST` - always use the 12-char abbreviated digest, even if version available
   - `VERSION_DIGEST` - use a `version:1234567890ab` style combo of version and digest id where both available

If the chosen option isn't available, they'll all fail back to `auto`. A diagnostic code, `version-select` that ties back to precisely which [code])(https://github.com/rhizomatics/updates2mqtt/blob/main/src/updates2mqtt/integrations/docker.py#L533) used is included in the attributes.

## Silencing Containers

If there are containers which are changing very frequently with development builds, or for other reasons
shouldn't be published to Home Assistant, then use the `image_ref_select` in configuration.

They will still be published to MQTT but not to the Home Assistant MQTT Discovery topic.

```yaml title="config.yaml snippet"
docker:
  enabled: true
  image_ref_select:
    exclude:
      - .*:nightly
      - .*:dev
```

Alternatively, set `UPD2MQTT_IGNORE` flag on the container itself to completely ignore it.

## API Throttling

Docker API has [usage limits](https://docs.docker.com/docker-hub/usage/) which may be triggered if there are many containers ( and other registries will have similar).

`updates2mqtt` will back off if a `429` Too Many Requests response is received, and pause for that specific registry for the requested number of seconds. There's a default in `docker` config of `default_api_backoff` applied if the backoff can't be automatically determined.

The main technique to avoid throttling is caching of responses, and fortunately many of the calls are cache friendly, such as the manifest retrieval. By default, responses will be cached as suggested by the registry API service ([explanation](https://hishel.com/1.1/specification/#how-it-works)), however this can be overridden with these options:

| Config Key | Default | Comments |
| ---------- | ------- | -------- |
| `mutable_cache_ttl` | None | This is primarily the fetch of `latest` or similar tags to get new versions |
| `immutable_cache_ttl` | 7776000 (90 days) | This is for anything fetched by a digest, such as image manifests. The only limitation for these should be storage space |
| `token_cache_ttl` | None | Caching for authorization tokens, `docker.io` is good for 300 seconds, not all registries publish the life in the response |

The cache, using [Hisel](https://hishel.com), is automatically cleaned up of old entries once the TTL (Time to Live) has expired.

The other approach can be to reduce the scan interval, or ignore some of the containers.

#### Icon Sources

Updates look nicer in Home Assistant with a suitable icon. Updates2mqtt comes
pre-packaged with some common ones, in `common_packages.yaml`, and can automatically fetch them (and release links) for the popular [linuxserver.io](https://www.linuxserver.io) packages.  

If you have something not covered, here are some good places to look for self-hosted app icons:

- [Homarr Dashboard Icons](https://github.com/homarr-labs/dashboard-icons)
- [Self Hosted Icons](https://selfh.st/icons/) ([repo](https://github.com/selfhst/icons))
- [Simple Icons](https://github.com/simple-icons/simple-icons)
- [Tabler Icons](https://tabler.io/icons)
- [Papirus Icons](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
- [Homelab SVG Assets](https://github.com/loganmarchione/homelab-svg-assets)

