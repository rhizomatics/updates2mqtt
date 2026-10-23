# Roadmap

## Major Features

- Some form of `apt` support, at least publishing security updates required
- Remote config changes (see [#18](https://github.com/rhizomatics/updates2mqtt/issues/18))

## Minor

- Improve presentation within HA
- XXXX Docker Image not Docker Image for XXXX

## Migrate off Omegaconf

- Pydantic used for `anpr2mqtt` already
- Fully expose config as env vars
  - env vars will change to a SECTION\_\_VAR form
  - require a backward compatible form
- Good CLI support
  - Though other projects use `click`
