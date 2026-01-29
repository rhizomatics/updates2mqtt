# Customizing Containers

Each container can be customized, so that when it appears in Home Assistant it has an appropriate logo for its icon, and useful release notes. Some of this is done by pre-loaded metadata, in `common_packages.yaml`, by API exploration or inference, and some needs to be done locally, especially for more unusual components.

## Logos and Release Notes

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

By default, configurable using `version_policy` in the Docker section of the config, it uses an `auto` version policy that will choose the most meaningful, and fall back to digests where versions aren't available (usually via image labels/annotations). This will also take into account where updates are throttled, or a pinned digest declared in the container.

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


## Icon Sources

Updates look nicer in Home Assistant with a suitable icon. Updates2mqtt comes
pre-packaged with some common ones, in `common_packages.yaml`, and can automatically fetch them (and release links) for the popular [linuxserver.io](https://www.linuxserver.io) packages.  

If you have something not covered, here are some good places to look for self-hosted app icons:

- [Homarr Dashboard Icons](https://github.com/homarr-labs/dashboard-icons)
- [Self Hosted Icons](https://selfh.st/icons/) ([repo](https://github.com/selfhst/icons))
- [Simple Icons](https://github.com/simple-icons/simple-icons)
- [Tabler Icons](https://tabler.io/icons)
- [Papirus Icons](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme)
- [Homelab SVG Assets](https://github.com/loganmarchione/homelab-svg-assets)

## Environment Variables

The following environment variables can be used to configure containers for `updates2mqtt`:

| Env Var                    | Description                                                                                  | Default         |
|----------------------------|----------------------------------------------------------------------------------------------|-----------------|
| `UPD2MQTT_UPDATE`          | Update mode, either `Passive` or `Auto`. If `Auto`, updates will be installed automatically. | `Passive`       |
| `UPD2MQTT_PICTURE`         | URL to an icon to use in Home Assistant.                                                     | Docker logo URL |
| `UPD2MQTT_RELNOTES`        | URL to release notes for the package.                                                        |                 |
| `UPD2MQTT_GIT_REPO_PATH`   | Relative path to a local git repo if the image is built locally.                             |                 |
| `UPD2MQTT_IGNORE`          | If set to `True`, the container will be ignored by Updates2MQTT.                             | False           |
                        |                 |
| `UPD2MQTT_VERSION_POLICY` | Change how version derived from container label or image hash, `Version`,`Digest`,`Version_Digest` with default of `Auto`|
| `UPD2MQTT_REGISTRY_TOKEN` | Access token for authentication to container distribution API, as alternative to making a call to `token` service |

## Docker Labels

Alternatively, use Docker labels

| Label                          | Env Var                    |
|--------------------------------|----------------------------|
| `updates2mqtt.update`          | `UPD2MQTT_UPDATE`          |
| `updates2mqtt.picture`         | `UPD2MQTT_PCITURE`         |
| `updates2mqtt.relnotes`        | `UPD2MQTT_RELNOTES`        |
| `updates2mqtt.git_repo_path`   | `UPD2MQTT_GIT_REPO_PATH`   |
| `updates2mqtt.ignore`          | `UPD2MQTT_IGNORE`          |
| `updates2mqtt.version_policy`  | `UPD2MQTT_VERSION_POLICY`  |
| `updates2mqtt.registry_token`  | `UPD2MQTT_REGISTRY_TOKEN`  |


```yaml title="Example Compose Snippet"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    labels:
        updates2mqtt.relnotes: https://component.my.com/release_notes
```