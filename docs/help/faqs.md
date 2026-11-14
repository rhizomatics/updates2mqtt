---
tags:
  - faq
  - support
  - help
title: Frequently Asked Questions
description: Answers to common Updates2MQTT support queries
---
# Frequently Asked Questions

## Scanning

**Q**: How do I get Updates2MQTT to update Home Assistant every hour?

**A**: Set `scan_interval` in the Updates2MQTT config file to `3600`. This is the number of seconds Updates2MQTT sleeps between scans, and defaults to `10800` (3 hours).

```yaml title="conf/config.yaml"
scan_interval: 3600 # check for new versions every hour
```

Restart the container afterwards, for example `docker compose restart updates2mqtt`, to pick up the change. If you are running without a config file, see [Using a Config File](../configuration/using_a_config_file.md) for how to create one.

There's nothing to change in Home Assistant. It doesn't poll Updates2MQTT; the MQTT Update entities change as soon as Updates2MQTT publishes the results of each scan. The interval is measured from the end of one scan to the start of the next, so scans won't land exactly on the hour. A restart also triggers a fresh scan straight away.

Before going much lower than an hour, take a look at [Remote API Usage](../configuration/remote_api_usage.md#api-throttling), since registries like Docker Hub limit how many requests can be made per hour, especially when you have lots of containers.

**Q**: Why isn't my `UPDATES2MQTT_CHECK_INTERVAL` (or `UPDATES2MQTT_CONTAINERS`, `UPDATES2MQTT_ALLOW_UPDATES`) setting doing anything?

**A**: Updates2MQTT has never used these env vars, though they appear in some guides online. The scan interval is `scan_interval` in the config file, as above. All containers are checked by default, and can be left out with `image_ref_select` or the `updates2mqtt.ignore` label, see [Customizing Containers](../configuration/customizing_containers.md#silencing-containers). Updates are allowed with `allow_pull`, `allow_restart` and `allow_build` in the `docker` section of the [config file](../configuration/using_a_config_file.md). From v1.17.6, Updates2MQTT logs a warning at startup for any `UPDATES2MQTT_` env var, or unknown `U2M_` one.

## Containers

**Q**: Do I need to add `updates2mqtt` labels to every container?

**A**: No, every container is found and checked without any labels. Labels and `UPD2MQTT_` env vars are only for customizing a container, such as a logo, release notes link, [display name](../configuration/customizing_containers.md#display-names), or to have it ignored. See [Customizing Containers](../configuration/customizing_containers.md) for the full list. From v1.17.6, an unrecognised `updates2mqtt.` label is logged as a warning and ignored.

**Q**: Do I need a label to tell Updates2MQTT where the compose file is?

**A**: No. Docker Compose adds its own labels to each container it creates, including the directory it was run from, and Updates2MQTT uses those. There's no `updates2mqtt.compose_path` label. What's needed is for that directory to be mounted into the Updates2MQTT container at exactly the same path, so `/opt/HA:/opt/HA` rather than `/opt/HA:/compose`, otherwise it can report updates but can't restart the container. See [Installation](../installation.md#docker).

**Q**: Why does Home Assistant show a hash like `2d4f8c1e9a3b` rather than a version like `2.0.18`?

**A**: Updates2MQTT shows a version only when it can be sure which version the image is, usually from an image label or annotation, or a version tag. Images pulled as `latest` without a version label, such as `eclipse-mosquitto:latest`, leave only the digest to go on. Pinning a version tag in the compose file, e.g. `eclipse-mosquitto:2.0.18`, usually fixes this, or the `version_policy` setting or `updates2mqtt.version_policy` label can change how the version is chosen, see [Customizing Versions](../configuration/customizing_containers.md#customizing-versions).

**Q**: Does Updates2MQTT remove the old images after an update?

**A**: From v1.14.1 it can, but it's off by default. Set `remove_old_image: true` in the `docker` section of the [config file](../configuration/using_a_config_file.md), or the `U2M_REMOVE_OLD_IMAGE=true` env var, to remove the replaced image after a successful update, unless something else still uses it. Images left over from before, or from updates made outside Updates2MQTT, can be cleared with `docker image prune`.

**Q**: Something I'd changed inside a container went away after updating it. Why?

**A**: An update pulls the new image and recreates the container from it, exactly as `docker compose pull` and `docker compose up -d` would. Anything changed inside the old container, or a patched file from the image, is lost unless it lives on a mounted volume. If an app needs a step after every image update, such as re-applying a patch, either build it into a local image with a `Dockerfile` (see [Local Builds](../local_builds.md)), or keep it on the default `Passive` update policy, so it's only updated when you ask, and re-run the step afterwards.

## MQTT

**Q**: Why is there a `Disconnect failure from broker` warning when I update my MQTT broker container?

**A**: Recreating the broker container drops Updates2MQTT's connection to it, as it would any other MQTT client, and it reconnects automatically once the new broker is up. From v1.17.6, when this happens during an update it's logged as information rather than a warning. The update entity for the broker may show as unavailable for a moment while it reconnects.
