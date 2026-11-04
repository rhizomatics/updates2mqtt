# Roadmap

## Major Features

- Some form of `apt` support, at least publishing security updates required
- Remote config changes (see [#18](https://github.com/rhizomatics/updates2mqtt/issues/18))

## OCI Client
- ~~Upgrade OCI handling~~ done in 1.16.0, as the self-contained `updates2mqtt.oci` package, see [OCI Client](../oci_client.md)
- Publish separately to PyPI once the API has settled

## Minor
- Improve presentation within HA
  - XXXX Docker Image not Docker Image for XXXX [1.17.0]

## Migrate off httpx
- Consider niquests or httpx2
  - Hishel compatibility may be main issue, if so consider other caching
  - The OCI client already runs over niquests, so only its transport and caching hook need to change

## Migrate off Omegaconf

- Pydantic used for `anpr2mqtt` already
  - Fully expose config as env vars
    - env vars will change to a SECTION__VAR form
      - require a backward compatible form
  - Good CLI support
    - Though other projects use `click`
- Hold off on recent breaking OmegaConf release (q4/26)
