# Supply Chain Protection

Supply chain attacks, where a malicious release is published through a project’s own account or build pipeline, are increasingly common. An updater that installs releases as soon as they appear can spread one quickly, so Updates2MQTT is adding protections in stages. The full plan is in [RFC 0002](https://updates2mqtt.rhizomatics.org.uk/developer/design/rfcs/rfc0002-cyber_security/index.md).

From v1.18.0:

- Updates install exactly the image that was checked
- Updates2MQTT keeps a release history of when it first saw each image
- A version tag that’s been re-pushed with different content is reported
- An update *cooldown* is calculated and reported, but **not yet enforced**

## Installing exactly what was checked

Before v1.18.0, an update pulled the image’s tag, such as `eclipse-mosquitto:latest`, and got whatever the registry served at that moment. If the tag had moved since the last scan, that could be a different image from the one shown in Home Assistant.

Now an update pulls the exact digest found by the last scan, e.g. `eclipse-mosquitto@sha256:...`, then tags it locally as `eclipse-mosquitto:latest`, so Docker Compose and Portainer use it just as before. If that digest is no longer available from the registry, the update is abandoned rather than pulling the tag. The next scan picks up the new digest, and the update can be retried.

This applies when the registry check is enabled. Containers with a digest pinned in their compose file, e.g. `nginx:1.27@sha256:...`, are pulled by that ref, as before.

From v1.19.0:

- `docker compose up` is run with `--pull never`, so a service with `pull_policy: always` can’t have Compose pull the tag again, and replace the image that was checked
- If the last scan has no digest for the image, for example because the registry was rate limiting, an *Auto* update is skipped until a scan finds one. An update asked for from Home Assistant still pulls the tag, with a warning in the log

## Release history

Updates2MQTT records when it first saw each image digest, in `release_history.json` alongside `config.yaml` in the `conf` directory. It’s kept there because `conf` is always a mounted volume, so the history survives the Updates2MQTT container being recreated, including when it updates itself.

An image’s own creation time can’t be relied on, since it’s set by whoever built the image, and reproducible builds often set it to 1970. So the first sighting is used to measure how long a release has been around. If a GitHub release for the version was published later than that, the later time is used instead. Other sources only ever make the wait longer, never shorter.

The file is small, as only the latest 50 digests and versioned tags are kept for each image. If it’s deleted or becomes unreadable, Updates2MQTT starts a new one, and every image is treated as newly seen, which is the safe outcome. Upgrading to v1.18.0 starts the history, so every image counts as first seen on the day of the upgrade.

## Tag moves

A full version tag such as `2.0.18` usually refers to one fixed image. If Updates2MQTT sees a version tag pointing at a different digest from before, it logs it, and reports it in the `tag_moved` attribute with the previous and new digests and when it happened. The new digest also starts its own cooldown.

A moved tag isn’t always a problem. Some publishers, including Docker’s *Official Images* such as `postgres` and `nginx`, rebuild existing version tags to pick up base image security fixes. But it’s worth a look when it happens to an image you don’t expect it from. Tags that are meant to move, such as `latest`, `stable`, or a short version like `3.13`, aren’t reported.

## Update cooldown

A cooldown is how long a release has to have been around before it’s eligible to install. Most supply chain attacks are found and removed within days, so waiting a little avoids most of them, while still getting fixes reasonably quickly.

Observe only in v1.18.0

In v1.18.0 the cooldown is calculated and reported, but doesn’t hold anything back. Updates show and install exactly as before, and *Auto* updates still happen straight away. A future release will enforce it for *Auto* updates, after giving notice, see the [rollout plan](https://updates2mqtt.rhizomatics.org.uk/developer/design/rfcs/rfc0002-cyber_security/#rollout-phases). The attributes show what would have been held, to help choose a setting before then.

The default is 3 days. Change it for all containers in the `docker` section of the config file:

config.yaml snippet

```yaml
docker:
  cooldown: 72h # or e.g. 3d, 1w, 90m, or 0 to turn off
```

Units are `m` minutes, `h` hours, `d` days or `w` weeks, and a plain number is taken as hours. Or set it for one container with a label or env var, which takes precedence:

docker compose snippet

```yaml
    labels:
      updates2mqtt.cooldown: 7d
```

or `UPD2MQTT_COOLDOWN=7d` in the container’s environment. An invalid value is logged as a warning, and the `docker` setting is used instead.

### Cooldown attributes

When an update is available, its Home Assistant entity has a `cooldown` attribute:

| Attribute             | Meaning                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| `policy`              | The cooldown setting that applies, e.g. `3d`                                                          |
| `release_time`        | When the cooldown started                                                                             |
| `release_time_source` | `first_seen` from the release history, or `release_published` if a GitHub release was published later |
| `until`               | When the update becomes eligible                                                                      |
| `active`              | `true` while the update would be held                                                                 |
| `enforced`            | `false` in v1.18.0, as the cooldown is only reported                                                  |

These can be used in Home Assistant templates and automations, for example to show how long is left, or to only install updates whose cooldown has finished:

template example

```yaml
{{ state_attr('update.dockernuc_docker_mosquitto', 'cooldown').until }}
```

## Strict registry checks

Anything Updates2MQTT fetches from a registry by its digest, such as a platform’s image manifest or an image config, is always checked against that digest. But a scan looks an image up by its tag, such as `latest`, and the registry then says which digest the tag points to, in a response header that by default is trusted. That digest is the one shown in Home Assistant, recorded in the release history, and pulled by an update.

Strict mode checks it instead, refusing registry data it can’t verify:

- The digest a registry reports for a tag must match the manifest it serves
- A digest in an algorithm Updates2MQTT can’t compute is rejected, rather than trusted

config.yaml snippet

```yaml
docker:
  registry:
    strict: true
```

A registry that follows the OCI specification always passes these checks. If one fails, the image is shown with no update, and an error is logged, as either the registry or something between it and Updates2MQTT is serving content that isn’t what it claims to be.

Strict mode applies to the built-in registry client, the default `OCI_V2` and `OCI_V2_MINIMAL` values of `docker.registry.api`, not to `DOCKER_CLIENT`. It’s off by default for now. Further checks, such as image signatures, will be added to it as described in [RFC 0002](https://updates2mqtt.rhizomatics.org.uk/developer/design/rfcs/rfc0002-cyber_security/index.md).

## Related

- [Improving Security](https://updates2mqtt.rhizomatics.org.uk/configuration/security/index.md), including restricting who can send update commands over MQTT
- [RFC 0002 Cyber Security](https://updates2mqtt.rhizomatics.org.uk/developer/design/rfcs/rfc0002-cyber_security/index.md), for the full plan, including signature checks and image scanning
