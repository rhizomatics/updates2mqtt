# Roadmap

## Major Features

- Some form of `apt` support, at least publishing security updates required

## Migrate off Omegaconf

- Pydantic used for `anpr2mqtt` already
  - Fully expose config as env vars
    - env vars will change to a SECTION__VAR form
      - require a backward compatible form
  - Good CLI support
    - Though other projects use `click`
