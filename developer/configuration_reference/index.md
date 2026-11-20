# Configuration Reference

Generated from the OmegaConf structured config dataclasses in `updates2mqtt.config`, so it always matches the code. For how to write a config file, see [Using a Configuration File](https://updates2mqtt.rhizomatics.org.uk/configuration/using_a_config_file/index.md).

Each class is a block in `config.yaml`, and each attribute a key in that block, with its type and default as written in the source. Defaults written as `${oc.env:VAR,default}` are OmegaConf interpolations, read from environment variable `VAR` if set, otherwise `default`, and `MISSING` marks a mandatory value. Nested blocks default to the defaults of their own class.

{{ pagetree(siblings) }}

## Top Level

## Config

Root of `config.yaml`

### log

```python
log: LogConfig = field(default_factory=LogConfig)
```

Logging

### node

```python
node: NodeConfig = field(default_factory=NodeConfig)
```

This instance

### mqtt

```python
mqtt: MqttConfig = field(default_factory=MqttConfig)
```

MQTT broker connection

### homeassistant

```python
homeassistant: HomeAssistantConfig = field(
    default_factory=HomeAssistantConfig
)
```

Home Assistant integration

### docker

```python
docker: DockerConfig = field(default_factory=DockerConfig)
```

Docker containers

### github

```python
github: GitHubConfig = field(default_factory=GitHubConfig)
```

GitHub API access

### scan_interval

```python
scan_interval: int = 60 * 60 * 3
```

Seconds between scans

### packages

```python
packages: dict[str, PackageUpdateInfo] = field(
    default_factory=dict
)
```

Package metadata, keyed by package name, adding to or overriding the common packages

## Node

## NodeConfig

This Updates2MQTT instance, the `node` block

### name

```python
name: str = field(
    default_factory=lambda: os.getenv(
        "NODE_NAME",
        os.uname().nodename.replace(".local", ""),
    )
)
```

Unique name for this instance, used in topics and entity ids, from `NODE_NAME` or the host name

### git_path

```python
git_path: str = '/usr/bin/git'
```

Path to the git executable, used for local builds

### healthcheck

```python
healthcheck: HealthCheckConfig = field(
    default_factory=HealthCheckConfig
)
```

Heartbeat settings

## HealthCheckConfig

Heartbeat publishing, the `node.healthcheck` block

### enabled

```python
enabled: bool = True
```

Publish heartbeats

### interval

```python
interval: int = 300
```

Interval in seconds to publish heartbeat message, 0 to disable

### topic_template

```python
topic_template: str = "healthcheck/{node_name}/updates2mqtt"
```

Heartbeat topic, with `{node_name}` replaced by the node name

### heartbeat_file

```python
heartbeat_file: str = field(
    default_factory=lambda: (
        f"${{oc.env:U2M_HEARTBEAT_FILE,{default_heartbeat_file()}}}"
    )
)
```

Local file for the container healthcheck, holding when the app last ran its heartbeat, and when the broker last acknowledged one, so no separate MQTT connection is needed to check it; empty to not write one. `U2M_HEARTBEAT_FILE` sets it for both the app and `healthcheck.sh`, which can’t read this config file

## Logging

## LogConfig

Logging, the `log` block

### level

```python
level: LogLevel = (
    "${oc.decode:${oc.env:U2M_LOG_LEVEL,INFO}}"
)
```

Log level, from `U2M_LOG_LEVEL`

### json

```python
json: bool = False
```

Use JSON structured logging for non-interactive running

## LogLevel

### DEBUG

```python
DEBUG = 'DEBUG'
```

### INFO

```python
INFO = 'INFO'
```

### WARNING

```python
WARNING = 'WARNING'
```

### ERROR

```python
ERROR = 'ERROR'
```

### CRITICAL

```python
CRITICAL = 'CRITICAL'
```

## GitHub

## GitHubConfig

GitHub API access for release notes, the `github` block

### access_token

```python
access_token: str | None = None
```

Personal access token, to raise the GitHub API rate limit

### mutable_cache_ttl

```python
mutable_cache_ttl: int = 60 * 60 * 15
```

Seconds to cache GitHub release lookups
