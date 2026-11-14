# Design Principles

## MQTT
- First class MQTT usage
  - Support MQTT v5 with full backward compatibility to 3.1
  - Don't allow 3.1 gaps to prevent features of v5 being used

## Clients

- Home Assistant is the primary client, and alignment with Home Assistant features and standards will be maintained
- Home Assistant design doesn't preclude the usablity for any other purpose
- It should be feasible to use the data from a simple shell script, e.g. using `mosquitto_sub`

## Cyber Security

- The default install of `updates2mqtt` will be more secure than a user casualy making `docker pull` or similar commands themselves
- See [RFC0002](./rfcs/rfc0002-cyber_security.md)

## Architecture

- `podman` is supported equally to native `docker` as primary installs
  - `portainer` is supported, but not as a primary install
  - Move towards `podman` as preferred, given its root-less usage
  - Maintain OCI standards wherever feasible, and document where divergence required for poor upstream implementation
  - `compose` type installations are recommended but not essential
- Architecture is designed for multiple artefact types, of which OCI images are the first
- Keep open the possibility of spinning out the OCI client, since it exists on updates2mqtt because there was no good live pypi alternative
  - See [RFC0001](./rfcs/rfc0001-oci_client.md)
- The configuration will be as consistent as possible across files, environment variables and command line arguments
  - Everything can be set via environment variables, and they can also selectively override file config
  - See [RFC0003](./rfcs/rfc0003-configuration.md)

## AI
- The project has a pragmatic approach to AI usage
  - It is expected that many users will have Claude Code, Muse or similar agents do their install for them and debug issues
  - Documentation and config will be easily accessible to agents by default, and additional skills offered where it makes sense
    - Use https://github.com/rhizomatics/agent-plugins
- Move towards automated PR and security review as an initial filter
  - PRs will continue to also be manually reviewed