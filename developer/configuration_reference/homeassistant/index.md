# Home Assistant

The `homeassistant` block. See [Home Assistant Integration](https://updates2mqtt.rhizomatics.org.uk/home_assistant/index.md) for how these are used.

## HomeAssistantConfig

Home Assistant integration, the `homeassistant` block

### discovery

```python
discovery: HomeAssistantDiscoveryConfig = field(
    default_factory=HomeAssistantDiscoveryConfig
)
```

MQTT discovery settings

### state_topic_suffix

```python
state_topic_suffix: str = 'state'
```

Reserved, the state topic currently always ends in `state`

### device_creation

```python
device_creation: bool = True
```

Group each node’s update entities under a Home Assistant device

### force_command_topic

```python
force_command_topic: bool = False
```

Publish a command topic even where an update can’t be installed

### extra_attributes

```python
extra_attributes: bool = True
```

Source the entity’s attributes from the general topic, using `json_attributes_topic`

### area

```python
area: str | None = None
```

Suggested area for the Home Assistant device

### release_summary_max_size

```python
release_summary_max_size: int = 6144
```

Characters of release notes to publish before truncating

## HomeAssistantDiscoveryConfig

Home Assistant MQTT discovery, the `homeassistant.discovery` block

### prefix

```python
prefix: str = 'homeassistant'
```

Discovery topic prefix, matching Home Assistant’s MQTT integration setting

### enabled

```python
enabled: bool = True
```

Publish discovery config topics
