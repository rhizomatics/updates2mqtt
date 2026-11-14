---
title: What's New
---

# 1.17.5
## 🐞Bug Fixes
- Warnings and errors from libraries such as `httpx`, `docker` and `paho` are now logged in the same format as the app's own logs, with a level, timestamp and logger name, rather than as a bare message that log collectors couldn't parse

# 1.17.4
## 🐞Bug Fixes
- Rebuilds of an image with an unchanged version label, such as `master` or `nightly`, now show as e.g. `master:967348dc33c5` to `master:84c6c5ee889a` in the update, matching the format used once installed, rather than switching to image timestamps while an update is waiting
  - The installed image id and registry image are now compared on their config digests, where previously the registry manifest digest never matched the local image id
- Home Assistant no longer lets the extra attributes topic override the update entity's own `installed_version`, `latest_version` and `title`, which could briefly show an update as available with identical versions
- Images reused without a registry lookup, e.g. pinned or with registry checks disabled, keep their version and creation timestamp, which were being passed into the wrong fields

# 1.17.3
## ✨ Enhancements
### Docker image
- Docker CLI, `buildx` and `compose` now come from Docker's own release images rather than its `apt` repository, which lags upstream releases. This picks up current releases with CVEs fixed, e.g. for `compress`
  - Versions are pinned in the `Dockerfile`, currently Docker CLI 29.9.3, `buildx` 0.38.2 and `compose` 5.7.0, and kept up to date by Dependabot
  - `uv`, used only to build the image, is also pinned rather than taking `latest`
- Weekly image rebuilds no longer count vulnerabilities in the Docker tools, since only a version bump, not a rebuild, can fix those
## 🐞Bug Fixes
- Registry cache database is now closed at shutdown, once no update is still running
## 📝 Other changes
- Improvements to test stability
- Stricter `mypy` type checking, configured in `pyproject.toml` so editors, `uv run mypy` and pre-commit all agree

# 1.17.2
## 🐞Bug Fixes
- Container level `updates2mqtt.version_policy` label, or `UPD2MQTT_VERSION_POLICY` env var, now takes effect whatever its case, e.g. `Digest` as documented, where previously only an exact uppercase value worked and others were silently ignored
- The official `ubuntu` image keeps its own version, rather than it being suppressed by the check that stops an Ubuntu base image's version leaking into images built on it, such as `greptime/greptimedb`
- Test coverage improved, esp for MQTT module

# 1.17.1
## ✨ Enhancements
- Huge update to *Common Packages*, with 85 more common self-hosted images
- `hotio` auto package enrichment
## 📝 Other changes
- `hishel` explicitly capped at `<2.0.0` version for now


# 1.17.0
## ✨ Enhancements
### Home Assistant
- Update entity titles now lead with the container name, e.g. `frigate Docker Image on nuc` rather than `Docker Image for frigate on nuc`, so they read and sort better in Home Assistant
### Container registries
- New registry client, in the self-contained `updates2mqtt.oci` package, ready to publish as a separate library
- Private registries supported, using `docker login` credentials from the Docker config file, including credential helpers and identity tokens
  - Logging in to Docker Hub also gets its higher rate limit
  - See [Private Registries](configuration/remote_api_usage.md#private-registries)
## 🐞Bug Fixes
- A container caught mid-recreate by `docker compose`, briefly renamed `<id>_<name>`, is no longer published as an extra update entity
- Topic cleaning no longer logs every other integration's update topic it skips, giving a count in its summary instead
- Content fetched by digest is checked against it
- Multi-platform images now match the platform variant, e.g. `arm/v7` rather than `arm/v6`
## 📝 Other changes
- Registry authentication now follows each registry's own challenge, rather than a built in list of token services, so registries not specially known also work
- Image digest now worked out from the content where a registry doesn't send it
- Local registries on `localhost` are reached over plain http, as Docker does
- One long-lived, cached connection to registries, rather than a new one for each request
- `u2m-cli` adds `referrers=<image>` to list signatures, SBOMs and other artifacts attached to an image
- Registry API stats count the expected first `401` challenge from each registry as an auth challenge, not an error

# 1.16.0
## ✨ Enhancements
### Parallel updates
- Updates now run in parallel, rather than one at a time, up to `max_concurrent_updates` (default 3, or `U2M_MAX_CONCURRENT_UPDATES` env var)
  - Further updates show as in progress in Home Assistant while waiting for a free slot
  - Compose restarts and builds, and Portainer redeploys, are still one at a time within the same project or stack
- `docker pull`, `git pull`, `docker compose build`/`up` and Portainer redeploys no longer block the service while they run, so heartbeats, scans and other commands carry on
- Container scans, and topic cleaning after a scan, also no longer block the service
- `docker compose` and `git` are now run directly rather than through a shell
### Self update
- When Updates2MQTT updates its own container, a short-lived helper container now runs the `docker compose up`, so the recreation completes even though the old container is stopped part way through
  - Other updates in progress finish first, and new update requests are ignored until the restart
  - The new container logs the helper's result and removes it
  - Falls back to the previous in-container recreate if the helper can't be started
## 📝 Other changes
### Shutdown
- SIGTERM and SIGINT now stop the service promptly, including between scans, cancelling in-flight updates and marking the node offline before exiting
### Docker Image Shrink
- Remove build tooling and full docker engine from final Docker image
- Image now smaller, and has fewer things to flag as false positives in an image scan
  
# 1.15.0
## ✨ Enhancements
### Home Assistant
- Entities now report availability on MQTT broker
  - Updates2MQTT publishes 
    - `online` to `updates2mqtt/<node>/availability` when it connects
    - `offline` when it shuts down,
    - sets `offline` as its MQTT last will, so the broker publishes it if the service crashes or is killed.
  -  Every discovery config includes this as its `availability_topic`
  - **Behaviour change**: while Updates2MQTT is down, including while it is updating its own container, its update entities in Home Assistant show as *unavailable* rather than keeping their last state. They come back when it reconnects
  - See [Home Assistant Integration](./home_assistant.md#availability)

# 1.14.4
## 🐞Bug Fixes
### Security
  - Build chain certificate update for eMudhra intermediate ca certs issue
  - Container rebuilt with latest `uv` version and os `ca-certificates` for eMudhra issue
## 📝 Other changes
- CI workflow now has a docker container integration test

# 1.14.3
## 🐞Bug Fixes
### Portainer
- Wait for the stack deployment to complete, using the stack's deployment status, rather than treating Portainer accepting the redeploy request as success. 
  - Portainer 2.41+ now deploys in the background, so a failed deployment was previously reported as a successful update. Failures now log Portainer's error message, and a redeploy requested while another deployment of the stack is in progress waits for that to finish first
## 📝 Other changes
- Added dind test framework to automate integration testing for compose and portainer

# 1.14.2
## ✨ Enhancements
- A default `config.yaml` is no longer auto-generated when `MQTT_USER` and `MQTT_PASS` are set as env vars, since the env vars already fully describe the config, and it can create an unnecessary file. Set `U2M_AUTOGEN_CONFIG=1` to generate it anyway
## 🐞Bug Fixes
- After an update, Home Assistant could keep showing the old installed version until the next scan or a restart of Updates2MQTT
 - Most likely when updating via Portainer, where the redeploy can return before the container is recreated. 
 - The post-update rescan now waits (up to 60s) for the container to be running the newly pulled image before republishing its state

# 1.14.1
## ✨ Enhancements
### Portainer
- New `PORTAINER_CA_CERTS` env var, or `ca_certs` in config, to verify Portainer with a private root CA
- New `PORTAINER_VERIFY_SSL` env var, as alternative to `verify_ssl` in config
### Docker
- Optionally remove the replaced image after a successful update, using `remove_old_image` in config or `U2M_REMOVE_OLD_IMAGE` env var
### CLI
- `mqtt=check` also reports the update and Portainer settings, with the env var each comes from, and checks the Portainer `ca_certs` file exists
## 🐞Bug Fixes
- When `PORTAINER_API_KEY` or `PORTAINER_URL` were set, an auto-generated config file copied their values into `config.yaml`, rather than referencing the env vars as for MQTT settings
- [Without a Configuration File](./configuration/zero_config_file.md) docs listed `MQTT_PASSWORD` rather than the correct `MQTT_PASS` env var
## 📚 Documentation
- README and translations updated for Portainer support and old image removal

# 1.14.0
## ✨ Enhancements
### Portainer
- Initial API support for Portainer is provided, to bring it up to a similar level of functionality to the Docker Compose
  - Instructions and limitations at [Portainer Configuration](./configuration/portainer.md)
  - This is in Beta at present, so use with caution, and feedback where you have issues
## 📝 Other changes
- Automated testing on every build extended to Py3.15, and backwards to Py3.14
- Omegaconf restricted to `<2.4.0` as [new release](https://github.com/hydra-ecosystem/omegaconf/releases#release-v2.4.0) broke many tests. Reviewing use of `pydantic` instead for config before embarking on upgrade for omegaconf (project has been moribund since 2022)

# 1.13.0
## ✨ Enhancements
### Compose
- Compose project name now passed with `-p` when restarting or building, so projects whose name differs from their directory are recreated in place rather than duplicated
- `can_restart` now only reported when the compose working directory is actually visible inside the Updates2MQTT container
- New `compose_path_found` and `compose_project` attributes in MQTT `installation_detail`, and a warning logged when the compose directory can't be seen
### Portainer
- Portainer stacks detected from their `/data/compose/<id>` working directory, with a `portainer_stack_id` attribute added
- Containers in Portainer stacks can now be updated from Home Assistant, by redeploying the stack through the Portainer API ( [#18](https://github.com/rhizomatics/updates2mqtt/issues/18) )
  - Configure with `PORTAINER_URL` and `PORTAINER_API_KEY` env vars, or a `docker.portainer` section in the config file
  - Images are pulled locally first, and the redeploy doesn't pull, so only the updated containers are recreated
  - Web editor and Git stacks supported, Portainer itself and its agents are excluded

# 1.12.0
## ✨ Enhancements
### MQTT TLS
- More MQTT configuration available as environment variables
  - `MQTT_TLS_MODE` ( `on`,`off` or `insecure`)
  - `MQTT_TRANSPORT` ( `tcp`, `unix` or `websockets`)
  - `MQTT_CERT_REQUIRED` ( `CERT_REQUIRED`, `CERT_OPTIONAL`, `CERT_NONE` ) 
### CLI
- CLI with no arguments now shows help instead of trying to look up a `frigate` container, and a Docker connection failure gives a one line error rather than a stack trace
- New `mqtt=check` CLI command to show MQTT settings (without secrets) and test the broker connection
## 🐞Bug Fixes
- Rejected MQTT credentials at startup no longer wait for the full connection timeout
## 📝 Other changes
- Debug CLI script renamed from `cli` to `u2m-cli`, so it can be installed with `uv tool install updates2mqtt`

# 1.11.1
## 🐞Bug Fixes
- Fix for [#175](https://github.com/rhizomatics/updates2mqtt/issues/175) (OCI_V2 lookup never finds an update for single-platform images without an image index)
- OCI_V2_MINIMAL mode now fixed
- CLI fixed for case sensitive API names
- Tag responses could be over-cached, registry `mutable_cache_ttl` now defaults to 1 hour
  - Older caches entries will persist until cache directory cleaned out
- Image creation time now read correctly from OCI image config
- Python 3.13 compatibility issue found in config validation and resolved
## 📝 Other changes
- Minor dependency update
- Documentation site generation switched from mkdocs to ProperDocs
- `ty` now also used for type checking, and minor type fixes made

# 1.11.0
## ✨ Enhancements
### MQTT TLS
- `ca_certs` is now optional for TLS, so can default to built-in certificate authorities where broker has a public verified cert
- `tls_mode` can be `on`,`off` or `insecure`
- TLS keyfile password can be set using `client_key_password` in config or `MQTT_CLIENT_KEY_PASS` env var
### MQTT Transport
- The default `tcp` transport can now be overridden by using `transport` in MQTT configuration, for either `websockets` or `unix`
## 📝 Other changes
- Minor dependency update
- Upgraded ruff to `0.16.0` and enabled its huge number of new checks in that version, fixing minor issues identified

# 1.10.0
## ✨ Enhancements
- TLS support for MQTT brokers
  - Password is no longer mandatory, to support client-cert auth, or no-auth
- Node name now defaults to $NODE_NAME if set, where no node name in config, failing which back to `os.uname()` as before
- Added more common Docker images, including Valkey, OpenClaw and Vaultwarden
## 📝 Other changes
- Dependency refresh

# 1.9.7
## ✨ Enhancements
- Add configurable MQTT keep alive, defaulting to 30 secs (previously hardcoded to 60s)
- Moved connection log line back to debug
- MQTT QoS changed to 1, so queued messages are resent if there is a disconnect. QoS logged.
- Reduce MQTT login churn where broker keep alive <= client keep alive

# 1.9.6
## ✨ Enhancements
- MQTT now has a `connect_timeout` defaulting to 10 seconds, and will wait for this before attempting to publish scan updates
## 🐞Bug Fixes
- Drop duplicate update commands when update for that component already in hand

# 1.9.5
## ✨ Enhancements
- Additional common packages added for logos and repos, including MariaDB and Redis
- Cache age stats easier to understand
- Common packages can have a list of image names
- Improve self-bounce behavior, allow more time for command to complete before exit
## 🐞Bug Fixes
- Clean up lingering in progress state from previous update
## 📝 Other changes
- Dependencies update
- Replace TaskGroup with simpler `await` usage so MQTT updates appear as they happen rather than in bulk at end of scan

# 1.9.4
## ✨ Enhancements
- More defensive access to linuxserver.io docker image info to handle missing fields, prompted by changes to HomeAssistant image in early May 2026
- Better defensive data access on registry manifests, versions, labels, annotations
## 📝 Other changes
- Improved test coverage

# 1.9.3
## ✨ Enhancements
### Logging
- New option to emit JSON structured logs when running as server (not attached to terminal)
## 📝 Other changes
- Loggers cached as per structlog best practice, and colour switched off for headless tty
## 🐞Bug Fixes
- Fixed stacktrace logs on server having `rich` library's box drawing special chars

# 1.9.2
## 🐞Bug Fixes
- Fix handling of expired Github access token

# 1.9.1
## ✨ Enhancements
- Translations for Dutch, French, German, Hindi, Italian, Japanese, Polish, Portuguese, Simplified Chinese and Spanish
- Vertalingen voor Nederlands, Traductions en français, Übersetzungen auf Deutsch, हिंदी में अनुवाद, Traduzioni in italiano, 日本語の翻訳, Tłumaczenia po polsku, Traduções em português, 简体中文翻译 en traducciones al español

# 1.9.0
## ✨ Enhancements
- Use the GitHub package versions API for GHCR images without a valid tag in image
- CLI improved to allow single container dump
- Github API now has its own `cache_ttl` config
## 📝 Other changes
- Refactor GitHub API code to separate module

# 1.8.5
## ✨ Enhancements
- Initial clean of MQTT topic on startup to remove any hanging in-progress status
- Default max summary size now 6K
  - Truncation now logged

# 1.8.4
## ✨ Enhancements
### Release Info
- Default max summary size now 8K, to avoid Home Assistant warnings on state
  - This limit can be increased, or removed, if the Update entities are excluded from Home Assistant's state history

# 1.8.3
## ✨ Enhancements
- Release summaries can now have a max length, using `release_summary_max_size`, default 16k

# 1.8.2
## ✨ Enhancements
### Version Detection
- Tighten up auto and fallback rules for cases where digests don't match
- Use versions in tag where they are SemVer or casual versions
### CLI
- Added `dump=csv`, `dump=json` and `help` commands
### Common Packages
- Added EMQX, Mosquitto, Plex, Emby, Tailscale, AppWrite, Traefik, Grafana, Prometheus, WhatsUpDocker, Lychee and HomeAssistant

# 1.8.1
## ✨ Enhancements
### Home Assistant
- Re-publish state every scan to ensure fresh
- Main discovery and state message now better in sync on `in_progress` flag
- State not published during update if Home Assistant mode off
### Version Detection
- Version Policy now includes `TIMESTAMP` for image creation date/time, which is also now part of auto version algorithm
- Version policy can be also be set in `custom_packages.yaml` or in the `packages` section of config
- Detect common mis-configuration where ubuntu base layer version published as derived image version
### MQTT
- MQTT result code, MID and publish status logged at debug, and at warning if non-success result code

# 1.8.0
## ✨ Enhancements
### Package Info
- The `common_packages.yaml` that ships inside the Docker image can be extended, or overridden, using the `packages` section of the main config file
- Source platform will be inferred, and verified, for GitHub, Gitlab, Quay, LSCR and Codeberg
### Release Notes
- If the component tag doesn't match the release tag (e.g. `1.7.3` vs `v1.7.3`), an alt lookup will be made on latest github released, and used if the tag name on that release matches the expected tag, with a common `v`,`V`,`r` or `R` prefix
- A GitHub *personal access token* can now be added in the `github:` config section, which will increase number of API calls that can be made for release info before being throttled
- Release notes can be better guessed, subject to URL validation, for Gitlab and GitHub
### CLI
- Logging improved, with different default for container lookup, so there's always some output from commands
- Added a `tags` option to retrieve list of known tags in the registry
### Housekeeping
- MQTT topic clean overhauled - 
    - Now runs only after scan
    - Checks topics against current discoveries vs previous session key based check

# 1.7.3
## 🐞Bug Fixes
- Minor fix for stats reporting

# 1.7.2
## ✨ Enhancements
### API Stats
- OCI v2 API client maintains api stats per host, and errors per status code, with a cache hit ratio and avg elapsed time
### Container Registry Checks
- The Config document is now also pulled in, which means more images have annotations, nice versions and release notes
- `OCI_V2_MINIMAL` option to make only the calls needed for version checks
- Diagnostic code now distinguishes two ways that different digests are checked between old and new
- Stats now tallied for all registry URL calls, and periodically logged
### CLI
- Colourful and jq friendly JSON output
- Log level now defaults to WARNING to make it easier to pipe results to `jq`, can change to see headers using `log_level=DEBUG`
## 🐞Bug Fixes
- Fixed issues with docker.io fetches from CLI

# 1.7.1
## 📝 Other changes
- No code change, version changed to fix a pypi publish issue

# 1.7.0
## ✨ Enhancements
### OCI Container Registry APIs
- By default now uses the OCI v2 Distribution APIs rather than old Docker APIs via Docker SDK
   - Older method can be switched back on using `docker.registry.api: docker_client` configuration
   - Container registry also used where available to pull in annotations ( including 
a meaningful version ) using the OCI Distriubtion API
  - Docker, GitHub GHCR, Gitlab, LSCR, Microsoft MCR and Codeberg configured
  - Authentication logic to automatically adapt and retry dynamically for other platforms
  - Annotations will be sourced from the Index or Manifest, with priority for the (platform-specific) manifest
  - Digest matching adapts to different practices across repos
- Registries can now be selectively included/excluded using `registry_select` in Docker configuration section
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
- Version selection now has a diagnostic code, `version_basis`, that ties back to precisely which code used
### Local Docker Image Enrichment
- Metadata from local `org.opencontainers` labels published where available
- Added more packages to common-packages, vector and greptime
### Selective Home Assistant Discovery
- New `version_select` option in Docker config works like `image_ref_select` using the reported version instead
### Pinned Digests
- Better handling of tags with a pinned digest, e.g. `ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84`
### API Throttling
- Throttling fixed for TTL taken from remote API
- Docker provider shuffles the list of containers it scans so if there is aggressive throttling there isn't the same set of containers always getting scanned before the rate limit hits
### Caching
- Index and Manifest local cache age now reported on MQTT message
- Additional logging and defaults for caching
- Local cache TTL override can be removed by using `None` for cache_ttl in registry config
## 📝 Other changes
### py3.14
- Image now built with python 3.14 by default
- Tests update for py3.14 mock async changes

# 1.6.0
## ✨ Enhancements
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
## 📝 Other changes
- Many more test cases added, focusing on Docker and MQTT integration
- Self-bounce now recognized and attempts to set exit code to 1, though container may still override that

# 1.5.2
## 📝 Other changes
- Build backend changed to `uv_build`
- GitHub Actions workflows updated, including to new uv actions

# 1.5.1
## ✨ Enhancements
- `MQTT_VERSION` environment variable added, defaults to `3.11`
- `U2M_AUTOGEN_CONFIG` environment variable added to control auto-generation of config files and directories
- `U2M_LOG_LEVEL` environment variable added to set log level without config file
- Title generation for Docker images reverts to same whether HA device set or not
## 📝 Other changes
- Test added to ensure component always functions without a config file, if no env var present

# 1.5.0
## ✨ Enhancements
- Target specific service on docker compose commands, where available from `com.docker.compose.service` label
- Publication of `command_topic` for each discovery can now be forced with `force_command_topic` option
- More common packages: docker:cli
- Common packages can now match on the image ref rather than base name, for example `docker:cli`
- Common Packages now allow entries without all the values, initially `rtl_433` which lacks a logo
## 📝 Other changes
- Log level in config is now an enum, and forced to be upper case
- Removed unnecessary latest_version fields from config message, which also saves a redundant MQTT subscription
- Reduced log noise in INFO and increased logging detail for DEBUG

# 1.4.2
## ✨ Enhancements
- An `area` can be defined in the Home Assistant section of config and this will then be used as `suggested_area` for device
## 📝 Other changes
- Replace `origin` in config MQTT message with `device` for better HomeAssistant compatibility
- More testcases
## 📚 Documentation
- Icon and release note info added for Owntone, Nextcloud, n8n, and Homarr

# 1.4.1
## ✨ Enhancements
- More logging for Docker discovery on why Home Assistant doesn't show an update button
## 📝 Other changes
- `MqttClient` is now `MqttPublisher` to avoid confusion with actual MQTT client
- Task cleanup now only interrupts explicit list of tasks - healthcheck and discovery tasks
- More test cases

# 1.4.0
## ✨ Enhancements
- MQTT protocol can now be set, to one of `3.1`,`3.11` or `5`
- Debug messages now provided for `on_subscribe` and `on_unsubscribe` callbacks
## 📚 Documentation
- Troubleshooting, installation, configuration docs updated, images optimized

# 1.3.7
## ✨ Enhancements
- Improved initial setup when run without config or env vars for MQTT
## 📝 Other changes
- Minor test deps update and pyproject docs

# 1.3.6
## ✨ Enhancements
- Changed exit code on graceful shutdown to 143
- App now exits if the MQTT username / password is not authorized
- Improved handling of env vars, default config now assumes MQTT_HOST etc unless overridden
  - Will now run without a config if correct `MQTT_HOST`,`MQTT_USER`,`MQTT_PASS`,`MQTT_PORT` env vars set or match the defaults (`127.0.0.1:1883`)
- Deps update