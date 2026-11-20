# Interface Reference

Updates2MQTT’s external interface is MQTT. This page lists every topic it publishes or subscribes to, and the schema of each message, using the default topic names. For how Home Assistant uses them, see [Home Assistant Integration](https://updates2mqtt.rhizomatics.org.uk/home_assistant/index.md).

## Topic Names

Topics are built from these values, shown with their defaults:

| Placeholder     | Default                            | Setting                           |
| --------------- | ---------------------------------- | --------------------------------- |
| `<topic_root>`  | `updates2mqtt`                     | `mqtt.topic_root`                 |
| `<node>`        | host name, or `NODE_NAME`          | `node.name`                       |
| `<discovery>`   | `homeassistant`                    | `homeassistant.discovery.prefix`  |
| `<source_type>` | `docker`                           | set by the integration            |
| `<container>`   | container name, sanitized for MQTT | set by the integration            |
| heartbeat topic | `healthcheck/<node>/updates2mqtt`  | `node.healthcheck.topic_template` |

`<container>` holds only `A-Z`, `a-z`, `0-9`, `_`, `-` and `.`.

## Topic Summary

| Topic                                                                 | Direction | Payload    | Retained | QoS |
| --------------------------------------------------------------------- | --------- | ---------- | -------- | --- |
| `updates2mqtt/<node>/<source_type>/<container>`                       | publish   | JSON       | yes      | 1   |
| `updates2mqtt/<node>/<source_type>/<container>/state`                 | publish   | JSON       | yes      | 1   |
| `homeassistant/update/<node>_<source_type>_<container>/update/config` | publish   | JSON       | yes      | 1   |
| `updates2mqtt/<node>/availability`                                    | publish   | plain text | yes      | 1   |
| `healthcheck/<node>/updates2mqtt`                                     | publish   | JSON       | yes      | 1   |
| `updates2mqtt/<node>/<source_type>`                                   | subscribe | plain text | **no**   | any |

Which topics are published for a component depends on its publish policy:

| Publish policy  | General | State | Discovery config                                       |
| --------------- | ------- | ----- | ------------------------------------------------------ |
| `HomeAssistant` | yes     | yes   | yes, unless `homeassistant.discovery.enabled` is false |
| `MQTT`          | yes     | no    | no                                                     |
| `Silent`        | no      | no    | no                                                     |

On startup, Updates2MQTT reads back its own retained topics for the node and clears, by publishing an empty retained message, any for components it no longer finds, along with incomplete state messages and `in_progress` flags left behind by an interrupted update.

## General Topic

`updates2mqtt/<node>/docker/<container>`

The full description of a component, independent of Home Assistant. Home Assistant reads it as the update entity’s `json_attributes_topic`, unless `homeassistant.extra_attributes` is false. Published after every scan, and when an update starts and ends.

| Key                    | Type                    | Description                                                              |
| ---------------------- | ----------------------- | ------------------------------------------------------------------------ |
| `name`                 | string                  | Component name, as in the topic                                          |
| `node`                 | string                  | Node name                                                                |
| `provider.source_type` | string                  | Integration, e.g. `docker`                                               |
| `first_scan.timestamp` | ISO 8601 string         | When the component was first scanned since startup                       |
| `last_scan.timestamp`  | ISO 8601 string         | When it was last scanned                                                 |
| `last_scan.session`    | string                  | Id of the scan run                                                       |
| `last_scan.throttled`  | boolean                 | Registry lookups were throttled, so the latest version may be stale      |
| `scan_count`           | integer                 | Scans since startup                                                      |
| `installed_version`    | string or null          | Version running now                                                      |
| `latest_version`       | string or null          | Latest version available                                                 |
| `version_basis`        | string or null          | How the versions were derived, e.g. `version`, `digest`, `timestamp`     |
| `title`                | string                  | Display title                                                            |
| `can_update`           | boolean                 | Any of `can_build`, `can_restart` or pull is possible                    |
| `can_build`            | boolean                 | Can be rebuilt from a local git repo                                     |
| `can_restart`          | boolean                 | Can be recreated with `docker compose`                                   |
| `device_icon`          | string or null          | Material Design Icon, e.g. `mdi:docker`                                  |
| `update_type`          | string or null          | e.g. `Docker Image`, `Docker Build`                                      |
| `status`               | string                  | Component status                                                         |
| `features`             | list of strings         | `INSTALL`, `PROGRESS`, `RELEASE_NOTES`                                   |
| `entity_picture_url`   | string or null          | Logo URL                                                                 |
| `update_policy`        | string                  | `Auto` or `Passive`                                                      |
| `publish_policy`       | string                  | `HomeAssistant`, `MQTT` or `Silent`                                      |
| `version_policy`       | string                  | `AUTO`, `VERSION`, `DIGEST`, `VERSION_DIGEST` or `TIMESTAMP`             |
| `update.last_attempt`  | ISO 8601 string or null | When an update was last attempted                                        |
| `update.in_progress`   | boolean                 | An update is running now                                                 |
| `installation_detail`  | object or null          | How the component is installed, see [Docker detail](#docker-detail)      |
| `current_detail`       | object or null          | Installed artefact, see [Docker detail](#docker-detail)                  |
| `latest_detail`        | object or null          | Latest artefact, see [Docker detail](#docker-detail)                     |
| `release`              | object                  | Present only when release details are known, see [Release](#release)     |
| `cooldown`             | object or null          | Supply chain cooldown, see [Cooldown](#cooldown)                         |
| `tag_moved`            | object or null          | A versioned tag seen pointing at a new digest, see [Tag move](#tag-move) |

Consumers should ignore keys they don’t recognise, as new ones are added from time to time.

### Release

| Key               | Type                    | Description                                                                         |
| ----------------- | ----------------------- | ----------------------------------------------------------------------------------- |
| `captured`        | ISO 8601 string         | When these details were collected                                                   |
| `title`           | string or null          | Release title                                                                       |
| `version`         | string or null          | Release version                                                                     |
| `source_platform` | string or null          | `GitHub`, `GitLab`, `CodeBerg` or `SourceHut`                                       |
| `source_repo`     | string or null          | Source repository URL                                                               |
| `source`          | string or null          | Source URL for this release                                                         |
| `revision`        | string or null          | Source revision, e.g. git commit                                                    |
| `diff_url`        | string or null          | Link to the changes since the installed version                                     |
| `notes_url`       | string or null          | Release notes link                                                                  |
| `summary`         | string or null          | Release notes, possibly HTML, truncated to `homeassistant.release_summary_max_size` |
| `net_score`       | string or null          | Net reaction score on the release                                                   |
| `published`       | ISO 8601 string or null | When the release was published                                                      |

### Cooldown

See [Supply Chain Protection](https://updates2mqtt.rhizomatics.org.uk/configuration/supply_chain/index.md).

| Key                   | Type            | Description                                                  |
| --------------------- | --------------- | ------------------------------------------------------------ |
| `policy`              | string          | Cooldown setting, e.g. `3d`                                  |
| `release_time`        | ISO 8601 string | When the release is treated as published                     |
| `release_time_source` | string          | Where `release_time` came from                               |
| `until`               | ISO 8601 string | When the cooldown ends                                       |
| `active`              | boolean         | Still cooling down                                           |
| `enforced`            | boolean         | Updates are blocked until it ends, rather than only reported |

### Tag Move

| Key               | Type            | Description                      |
| ----------------- | --------------- | -------------------------------- |
| `tag`             | string          | The versioned tag, e.g. `2.0.18` |
| `previous_digest` | string          | Digest it pointed at before      |
| `digest`          | string          | Digest it points at now          |
| `moved`           | ISO 8601 string | When the move was seen           |

### Docker Detail

For `docker` components, `installation_detail` describes the container:

| Key                   | Type           | Description                                                        |
| --------------------- | -------------- | ------------------------------------------------------------------ |
| `container_name`      | string         | Docker container name                                              |
| `compose_path`        | string or null | Directory of the compose file                                      |
| `compose_path_found`  | boolean        | The compose file directory is reachable from Updates2MQTT          |
| `compose_project`     | string or null | Compose project name                                               |
| `compose_service`     | string or null | Compose service name                                               |
| `compose_version`     | string or null | Docker Compose version that created the container, from its labels |
| `portainer_stack_id`  | string         | Only present for Portainer stacks                                  |
| `git_local_timestamp` | string         | Only present for local builds                                      |
| `git_repo_path`       | string         | Only present for local builds                                      |

and `current_detail` and `latest_detail` describe an image:

| Key             | Type                    | Description                                |
| --------------- | ----------------------- | ------------------------------------------ |
| `captured`      | ISO 8601 string         | When these details were collected          |
| `image_ref`     | string or null          | Image reference, as in the compose file    |
| `name`          | string or null          | Untagged image name                        |
| `version`       | string or null          | Version, from labels, annotations or tag   |
| `image_digest`  | string or null          | Image digest                               |
| `repo_digest`   | string or null          | Repository digest                          |
| `repo_digests`  | string or null          | Repository digest, kept for compatibility  |
| `config_digest` | string or null          | Image config digest                        |
| `git_digest`    | string or null          | Git commit, for local builds               |
| `index_name`    | string or null          | Registry, e.g. `docker.io`, `ghcr.io`      |
| `tag`           | string or null          | Tag                                        |
| `pinned_digest` | string or null          | Digest the compose file pins the image to  |
| `tag_or_digest` | string or null          | Tag, or the pinned digest                  |
| `tags`          | list of strings or null | Other tags                                 |
| `origin`        | string or null          | Where the details came from, e.g. `OCI_V2` |
| `platform`      | string or null          | e.g. `linux/amd64`                         |
| `local_build`   | boolean                 | Built locally rather than pulled           |
| `error`         | string or null          | Lookup error                               |
| `throttled`     | boolean                 | The registry throttled the lookup          |
| `custom`        | object                  | Integration specific extras                |

### Example

Example: container jellyfin on node dockernuc

```json
{
  "name": "jellyfin",
  "node": "dockernuc",
  "provider": {"source_type": "docker"},
  "first_scan": {"timestamp": "2026-11-20T09:00:03+00:00"},
  "last_scan": {"timestamp": "2026-11-20T12:00:04+00:00", "session": "a41f9c", "throttled": false},
  "scan_count": 2,
  "installed_version": "10.11.2",
  "latest_version": "10.11.3",
  "version_basis": "version",
  "title": "Jellyfin",
  "can_update": true,
  "can_build": false,
  "can_restart": true,
  "device_icon": "mdi:docker",
  "update_type": "Docker Image",
  "status": "on",
  "features": ["INSTALL", "PROGRESS", "RELEASE_NOTES"],
  "entity_picture_url": "https://example.org/jellyfin.png",
  "update_policy": "Passive",
  "publish_policy": "HomeAssistant",
  "version_policy": "AUTO",
  "update": {"last_attempt": null, "in_progress": false},
  "installation_detail": {"container_name": "jellyfin", "compose_path": "/home/containers/jellyfin", "...": "..."},
  "current_detail": {"image_ref": "jellyfin/jellyfin:latest", "version": "10.11.2", "...": "..."},
  "latest_detail": {"image_ref": "jellyfin/jellyfin:latest", "version": "10.11.3", "...": "..."},
  "release": {"notes_url": "https://github.com/jellyfin/jellyfin/releases", "...": "..."},
  "cooldown": {"policy": "3d", "active": false, "enforced": false, "...": "..."},
  "tag_moved": null
}
```

## State Topic

`updates2mqtt/<node>/docker/<container>/state`

The Home Assistant [MQTT Update](https://www.home-assistant.io/integrations/update.mqtt/) state, the update entity’s `state_topic`. Only published for the `HomeAssistant` publish policy.

| Key                 | Type           | Description                                                          |
| ------------------- | -------------- | -------------------------------------------------------------------- |
| `installed_version` | string or null | Version running now                                                  |
| `latest_version`    | string or null | Latest version available                                             |
| `title`             | string         | Display title                                                        |
| `in_progress`       | boolean        | An update is running now                                             |
| `release_summary`   | string         | Only if known, truncated to `homeassistant.release_summary_max_size` |
| `release_url`       | string         | Only if known, release notes link                                    |

Example: container jellyfin on node dockernuc

```json
{
  "installed_version": "10.11.2",
  "latest_version": "10.11.3",
  "title": "Jellyfin",
  "in_progress": false,
  "release_url": "https://github.com/jellyfin/jellyfin/releases"
}
```

## Discovery Config Topic

`homeassistant/update/<node>_docker_<container>/update/config`

Home Assistant [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) config for the update entity.

| Key                        | Description                                                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `name`                     | Display title                                                                                                                        |
| `device_class`             | Always null                                                                                                                          |
| `unique_id`                | `<source_type>_<node>_<container>`                                                                                                   |
| `default_entity_id`        | `update.<node>_<source_type>_<container>`                                                                                            |
| `state_topic`              | The [state topic](#state-topic)                                                                                                      |
| `supported_features`       | As `features` in the [general topic](#general-topic)                                                                                 |
| `origin`                   | `name`, `sw_version` and `support_url` of Updates2MQTT                                                                               |
| `availability_topic`       | The [availability topic](#availability-topic)                                                                                        |
| `json_attributes_topic`    | The [general topic](#general-topic), unless `homeassistant.extra_attributes` is false                                                |
| `json_attributes_template` | Drops keys that would override the update entity’s own state                                                                         |
| `entity_picture`           | Logo URL, if known                                                                                                                   |
| `icon`                     | Device icon, if set                                                                                                                  |
| `device`                   | Shared by all of a node’s entities, unless `homeassistant.device_creation` is false, with `suggested_area` from `homeassistant.area` |
| `command_topic`            | The [command topic](#command-topic), if the component can be updated, or `homeassistant.force_command_topic` is true                 |
| `payload_install`          | `<source_type>\|<container>\|install`, if the component can be updated                                                               |

Example: container jellyfin on node dockernuc

```json
{
  "name": "Jellyfin",
  "device_class": null,
  "unique_id": "docker_dockernuc_jellyfin",
  "state_topic": "updates2mqtt/dockernuc/docker/jellyfin/state",
  "supported_features": ["INSTALL", "PROGRESS", "RELEASE_NOTES"],
  "default_entity_id": "update.dockernuc_docker_jellyfin",
  "origin": {
    "name": "dockernuc updates2mqtt",
    "sw_version": "1.19.0",
    "support_url": "https://github.com/rhizomatics/updates2mqtt/issues"
  },
  "availability_topic": "updates2mqtt/dockernuc/availability",
  "json_attributes_topic": "updates2mqtt/dockernuc/docker/jellyfin",
  "json_attributes_template": "{{ dict(value_json.items() | rejectattr('0', 'in', [...])) | to_json }}",
  "entity_picture": "https://example.org/jellyfin.png",
  "icon": "mdi:docker",
  "device": {
    "name": "dockernuc updates2mqtt",
    "sw_version": "1.19.0",
    "manufacturer": "rhizomatics",
    "identifiers": ["dockernuc.updates2mqtt"]
  },
  "command_topic": "updates2mqtt/dockernuc/docker",
  "payload_install": "docker|jellyfin|install"
}
```

## Command Topic

`updates2mqtt/<node>/docker`

Subscribed to, one per node and integration, to install updates. The payload is plain text:

```text
<source_type>|<container>|install[|<digest>]
```

- `<source_type>` has to match the topic, e.g. `docker`
- `install` is the only command
- `<digest>` is optional. When given, the command is ignored unless it matches the latest digest found by the last scan, `latest_detail.image_digest`, so a script or automation can be sure which release it installs

Commands must **not** be retained, and retained ones are ignored, so that an old command isn’t replayed when Updates2MQTT reconnects. A command for a component already being updated is ignored. Progress is reported through `in_progress` on the state and general topics.

Example: install the latest image for container jellyfin on node dockernuc

```shell
mosquitto_pub -t updates2mqtt/dockernuc/docker -m 'docker|jellyfin|install'
```

See [Security](https://updates2mqtt.rhizomatics.org.uk/configuration/security/index.md) for restricting who can publish commands.

## Availability Topic

`updates2mqtt/<node>/availability`

Plain text, `online` or `offline`, the Home Assistant defaults for `payload_available` and `payload_not_available`. `online` is published on every connection, `offline` on a clean shutdown, and `offline` is also the MQTT last will, so the broker publishes it if the connection is lost.

## Heartbeat Topic

`healthcheck/<node>/updates2mqtt`

Published every `node.healthcheck.interval` seconds, 300 by default, while `node.healthcheck.enabled` is true. Not under `<topic_root>`, so it can be monitored separately.

| Key               | Type                    | Description                     |
| ----------------- | ----------------------- | ------------------------------- |
| `version`         | string                  | Updates2MQTT version            |
| `node`            | string                  | Node name                       |
| `heartbeat_raw`   | number                  | Epoch seconds of this heartbeat |
| `heartbeat_stamp` | ISO 8601 string         | Time of this heartbeat, UTC     |
| `startup_stamp`   | ISO 8601 string         | When Updates2MQTT started       |
| `last_scan_stamp` | ISO 8601 string or null | When the last scan ran          |
| `scan_count`      | integer                 | Scans since startup             |

Example: node dockernuc

```json
{
  "version": "1.19.0",
  "node": "dockernuc",
  "heartbeat_raw": 1795165204.51,
  "heartbeat_stamp": "2026-11-20T12:00:04.510000+00:00",
  "startup_stamp": "2026-11-20T09:00:00.120000+00:00",
  "last_scan_stamp": "2026-11-20T12:00:04.200000+00:00",
  "scan_count": 2
}
```
