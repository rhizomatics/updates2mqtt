# Roadmap

## Major Features

- Cooldown and image scan integration for cyber hardening
- Some form of `apt` support, at least publishing security updates required
- Remote config changes (see [#18](https://github.com/rhizomatics/updates2mqtt/issues/18))
- Package up better for running as a `systemd` or `init.d` service
  - Possibly as a `.deb` or `.rpm`
- Update notification and possibly application for OpenWRT and similar ( Teltonika ) routers

## OCI Client
- ~~Upgrade OCI handling~~ done in 1.17.0, as the self-contained `updates2mqtt.oci` package, see [OCI Client](../oci_client.md)
- Publish separately to PyPI once the API has settled

## Minor
- Improve presentation within HA
  - XXXX Docker Image not Docker Image for XXXX [1.17.0]

## Migrate off httpx
- Consider niquests or httpx2
  - Hishel compatibility may be main issue, if so consider other caching
  - The OCI client already runs over niquests, so only its transport and caching hook need to change

## Migrate off Omegaconf

- Goals
  - Use a live, popular, config component with timely security updates and good help documentation
  - Offer consistent setup across environment variables and files
    - Everything can be done by env var, automatically
  - Easy debuggability and feedback on config issues
  - Possible value adds
   - Supporting CLIs with args/kwargs consistent with env vars and config files
   - Vault integration or similar for secure secret storage
  - Full backward compatibility with users existing env vars and config files
    - Possible option to auto-migrate config, though don't assume r/w access
  - Works well under Docker/Podman container as well as in PyPi library usage or systemd/init.d daemon

- First review the new OmegaConf and the wider Hydra framework its part of
- Pydantic used for `anpr2mqtt` already
  - Fully expose config as env vars
    - env vars will change to a SECTION__VAR form
      - require a backward compatible form
  - Good CLI support
    - Though other projects use `click`
- Hold off on recent breaking OmegaConf release (q4/26)
