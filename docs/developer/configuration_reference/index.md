---
description: Reference for every Updates2MQTT config.yaml setting, generated from the OmegaConf configuration classes.
---
# Configuration Reference

Generated from the OmegaConf structured config dataclasses in `updates2mqtt.config`, so it always
matches the code. For how to write a config file, see [Using a Configuration File](../../configuration/using_a_config_file.md).

Each class is a block in `config.yaml`, and each attribute a key in that block, with its type and
default as written in the source. Defaults written as `${oc.env:VAR,default}` are OmegaConf
interpolations, read from environment variable `VAR` if set, otherwise `default`, and `MISSING`
marks a mandatory value. Nested blocks default to the defaults of their own class.

{{ pagetree(siblings) }}

## Top Level

::: updates2mqtt.config.Config

## Node

::: updates2mqtt.config.NodeConfig

::: updates2mqtt.config.HealthCheckConfig

## Logging

::: updates2mqtt.config.LogConfig

::: updates2mqtt.config.LogLevel

## GitHub

::: updates2mqtt.config.GitHubConfig
