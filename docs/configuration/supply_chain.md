---
tags:
  - security
  - cooldown
title: Supply Chain Protection
description: How Updates2MQTT guards against supply chain attacks - installing exactly the checked image, release history, tag moves and update cooldowns
---
# Supply Chain Protection

Supply chain attacks, where a malicious release is published through a project's own account or
build pipeline, are increasingly common. An updater that installs releases as soon as they appear
can spread one quickly, so Updates2MQTT is adding protections in stages. The full plan is in
[RFC 0002](../developer/design/rfcs/rfc0002-cyber_security.md).

From v1.18.0:

- Updates install exactly the image that was checked
- Updates2MQTT keeps a release history of when it first saw each image
- A version tag that's been re-pushed with different content is reported
- An update *cooldown* is calculated and reported, but **not yet enforced**

## Installing exactly what was checked

Before v1.18.0, an update pulled the image's tag, such as `eclipse-mosquitto:latest`, and got
whatever the registry served at that moment. If the tag had moved since the last scan, that could
be a different image from the one shown in Home Assistant.

Now an update pulls the exact digest found by the last scan, e.g. `eclipse-mosquitto@sha256:...`,
then tags it locally as `eclipse-mosquitto:latest`, so Docker Compose and Portainer use it just as
before. If that digest is no longer available from the registry, the update is abandoned rather
than pulling the tag. The next scan picks up the new digest, and the update can be retried.

This applies when the registry check is enabled. Containers with a digest pinned in their compose
file, e.g. `nginx:1.27@sha256:...`, are pulled by that ref, as before.

## Release history

Updates2MQTT records when it first saw each image digest, in `release_history.json` alongside
`config.yaml` in the `conf` directory. It's kept there because `conf` is always a mounted volume,
so the history survives the Updates2MQTT container being recreated, including when it updates itself.

An image's own creation time can't be relied on, since it's set by whoever built the image, and
reproducible builds often set it to 1970. So the first sighting is used to measure how long a release has
been around. If a GitHub release for the version was published later than that, the later time is
used instead. Other sources only ever make the wait longer, never shorter.

The file is small, as only the latest 50 digests and versioned tags are kept for each image. If it's
deleted or becomes unreadable, Updates2MQTT starts a new one, and every image is treated as newly
seen, which is the safe outcome. Upgrading to v1.18.0 starts the history, so every image counts
as first seen on the day of the upgrade.

## Tag moves

A full version tag such as `2.0.18` usually refers to one fixed image. If Updates2MQTT sees a
version tag pointing at a different digest from before, it logs it, and reports it in the
`tag_moved` attribute with the previous and new digests and when it happened. The new digest also
starts its own cooldown.

A moved tag isn't always a problem. Some publishers, including Docker's *Official Images* such as
`postgres` and `nginx`, rebuild existing version tags to pick up base image security fixes. But
it's worth a look when it happens to an image you don't expect it from. Tags that are meant to move,
such as `latest`, `stable`, or a short version like `3.13`, aren't reported.

## Update cooldown

A cooldown is how long a release has to have been around before it's eligible to install. Most
supply chain attacks are found and removed within days, so waiting a little avoids most of them,
while still getting fixes reasonably quickly.

!!! info "Observe only in v1.18.0"

    In v1.18.0 the cooldown is calculated and reported, but doesn't hold anything back. Updates
    show and install exactly as before, and *Auto* updates still happen straight away. A future
    release will enforce it for *Auto* updates, after giving notice, see the
    [rollout plan](../developer/design/rfcs/rfc0002-cyber_security.md#rollout-phases).
    The attributes show what would have been held, to help choose a setting before then.

The default is 3 days. Change it for all containers in the `docker` section of the config file:

```yaml title="config.yaml snippet"
docker:
  cooldown: 72h # or e.g. 3d, 1w, 90m, or 0 to turn off
```

Units are `m` minutes, `h` hours, `d` days or `w` weeks, and a plain number is taken as hours. Or
set it for one container with a label or env var, which takes precedence:

```yaml title="docker compose snippet"
    labels:
      updates2mqtt.cooldown: 7d
```

or `UPD2MQTT_COOLDOWN=7d` in the container's environment. An invalid value is logged as a warning, and the
`docker` setting is used instead.

### Cooldown attributes

When an update is available, its Home Assistant entity has a `cooldown` attribute:

| Attribute | Meaning |
|---|---|
| `policy` | The cooldown setting that applies, e.g. `3d` |
| `release_time` | When the cooldown started |
| `release_time_source` | `first_seen` from the release history, or `release_published` if a GitHub release was published later |
| `until` | When the update becomes eligible |
| `active` | `true` while the update would be held |
| `enforced` | `false` in v1.18.0, as the cooldown is only reported |

These can be used in Home Assistant templates and automations, for example to show how long is
left, or to only install updates whose cooldown has finished:

```yaml title="template example"
{{ state_attr('update.dockernuc_docker_mosquitto', 'cooldown').until }}
```

## Related

- [Improving Security](security.md), including restricting who can send update commands over MQTT
- [RFC 0002 Cyber Security](../developer/design/rfcs/rfc0002-cyber_security.md), for the full plan, including signature checks and image scanning
