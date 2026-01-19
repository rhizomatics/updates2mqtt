# CHANGELOG

## 1.7.0
### Container Registry Enrichment
- Container registry will be accessed where available to pull in annotations ( including 
a meaningful version ) using the OCI Distriubtion API
  - Docker, GitHub GHCR and Codeberg explicitly supported
  - Authentication logic to automatically adapt and retry for other platforms
  - Annotations will be sourced from the Index or Manifest, with priority for the (platform-specific) manifest
### GitHub Release Enrichment
- Where an annotation points to a source URL and hash, this can be used to derive a 
`diff_url`, a direct link to the actual release notes, and a release summary pulled from the
Github source repo releases and passed onto Home Assistant
- A token can be provided, e.g. a Personal Access Token, at container level using `UPD2MQTT_REGISTRY_TOKEN`
- Common packages now have a `source_repo_url` and don't need a release notes URL too if on GitHub
### Version Policies
- Version policies available to make use of meaningful versions from annotations
   - `AUTO` will detect what looks like a SemVer and report only the meaningful version to HA
   - `VERSION`,`DIGEST` and `VERSION_DIGEST` can be used to fix on which fields to use
   - If the chosen option isn't available, next preference is for `version:digest` qualified version, falling back to whatever else is available
   - Version policy can be set at container level using `UPD2MQTT_VERSION_POLICY` env var or corresponding label
### Local Docker Image Enrichment
- Metadata from local `org.opencontainers` labels published where available
- Added more packages to common-packages, vector and greptime
### Selective Home Assistant Discovery
- New `version_select` option in Docker config works like `image_ref_select` but on the reported version instead

## 1.6.0
### MQTT Topics
- Separated out generic and Home Assistant specific topics
  - The *State*, *Command* and *Discovery* topics are strictly Home Assistant schema
  - The full discovery attributes are now published on their own topic
    - This can also be supplied as additional attributes to the Home Assistant Update entity
    - These can be turned off using the `extra_attributes` flag in `homeassistant` config
### Selective Home Assistant Discovery
- New `image_ref_select` option in Docker config
    - List of `include` strings or regular expressions, containers which don't match these won't be Home Assistant discoverable
    - List of `exclude` strings or regular expressions, containers which match these won't be Home Assistant discoverable
    - Containers not selected because of `image_ref_select` can still have an `Auto` update policy, so will be updated but not visible to Home Assistant
### Docker Labels
- Container customization can now be made by Docker labels instead of, or in addition to, env vars
### API Throttling
- Docker API now throttled per registry if receives 429 Too Many Requests
    - Uses `retry_after` header value, if missing or unreadable defaults to configurable `default_api_backoff`
### Local Builds
- General overhaul of some issues and improvements for local git repo image builds
- Version now synthesized in place of image version
    - `git:<short sha>` for current version
    - `git:<short sha>+<commits behind>` for latest version
- Auto update policy restricted to when there's an update to build
- For local git repos, install available check made now at discovery time
    - Install update in HA only appears if there's a pull available
### Internal
- Many more test cases added, focusing on Docker and MQTT integration
- Self-bounce now recognized and attempts to set exit code to 1, though container may still override that
## 1.5.2
### Internal
- Build backend changed to `uv_build`
- GitHub Actions workflows updated, including to new uv actions
## 1.5.1
- `MQTT_VERSION` environment variable added, defaults to `3.11`
- `U2M_AUTOGEN_CONFIG` environment variable added to control auto-generation of config files and directories
- `U2M_LOG_LEVEL` environment variable added to set log level without config file
- Title generation for Docker images reverts to same whether HA device set or not
- Test added to ensure component always functions without a config file, if no env var present
## 1.5.0
- Target specific service on docker compose commands, where available from `com.docker.compose.service` label
- Log level in config is now an enum, and forced to be upper case
- Removed unnecessary latest_version fields from config message, which also saves a redundant MQTT subscription
- Publication of `command_topic` for each discovery can now be forced with `force_command_topic` option
- More common packages: docker:cli
- Common packages can now match on the image ref rather than base name, for example `docker:cli`
- Reduced log noise in INFO and increased logging detail for DEBUG
- Common Packages now allow entries without all the values, initially `rtl_433` which lacks a logo
## 1.4.2
- Replace `origin` in config MQTT message with `device` for better HomeAssistant compatibility
- An `area` can be defined in the Home Assistant section of config and this will then be used as `suggested_area` for device
- Icon and release note info added for Owntone, Nextcloud, n8n, and Homarr
- More testcases
## 1.4.1
- More logging for Docker discovery on why Home Assistant doesn't show an update button
- More test cases
- `MqttClient` is now `MqttPublisher` to avoid confusion with actual MQTT client
- Task cleanup now only interrupts explicit list of tasks - healthcheck and discovery tasks
## 1.4.0
- MQTT protocol can now be set, to one of `3.1`,`3.11` or `5`
- Debug messages now provided for `on_subscribe` and `on_unsubscribe` callbacks
- Troubleshooting, installation, configuration docs updated, images optimized

## 1.3.7
- Improved initial setup when run without config or env vars for MQTT
- Minor test deps update and pyproject docs

## 1.3.6
- Changed exit code on graceful shutdown to 143
- App now exits if the MQTT username / password is not authorized
- Improved handling of env vars, default config now assumes MQTT_HOST etc unless overridden
  - Will now run without a config if correct `MQTT_HOST`,`MQTT_USER`,`MQTT_PASS`,`MQTT_PORT` env vars set or match the defaults (`127.0.0.1:1883`)
- Deps update