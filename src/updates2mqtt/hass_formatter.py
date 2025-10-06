from typing import Any

import structlog

import updates2mqtt
from updates2mqtt.model import Discovery

log = structlog.get_logger()
HASS_UPDATE_SCHEMA = [
    "installed_version",
    "latest_version",
    "title",
    "release_summary",
    "release_url",
    "entity_picture",
    "in_progress",
    "update_percentage",
]


def hass_format_config(
    discovery: Discovery, object_id: str, node_name: str, state_topic: str, command_topic: str | None, session: str
) -> dict[str, Any]:
    config = {
        "name": f"{discovery.name} {discovery.source_type} on {node_name}",
        "device_class": None,  # not firmware, so defaults to null
        "unique_id": object_id,
        "state_topic": state_topic,
        "source_session": session,
        "supported_features": discovery.features,
        "entity_picture": discovery.entity_picture_url,
        "icon": discovery.device_icon,
        "can_update": discovery.can_update,
        "can_build": discovery.can_build,
        "can_restart": discovery.can_restart,
        "update_policy": discovery.update_policy,
        "latest_version_topic": state_topic,
        "latest_version_template": "{{value_json.latest_version}}",
        "origin": {
            "name": "updates2mqtt",
            "sw_version": updates2mqtt.version,
            "support_url": "https://github.com/rhizomatics/updates2mqtt/issues",
        },
    }
    if command_topic:
        config["command_topic"] = command_topic
        config["payload_install"] = f"{discovery.source_type}|{discovery.name}|install"
    if discovery.custom.get("git_repo_path"):
        config["git_repo_path"] = discovery.custom["git_repo_path"]
    config.update(discovery.provider.hass_config_format(discovery))
    return config


def hass_format_state(discovery: Discovery, node_name: str, session: str, in_progress: bool = False) -> dict[str, Any]:  # noqa: ARG001
    title: str = (
        discovery.title_template.format(name=discovery.name, node=node_name) if discovery.title_template else discovery.name
    )
    state = {
        "installed_version": discovery.current_version,
        "latest_version": discovery.latest_version,
        "title": title,
        "in_progress": in_progress,
    }
    if discovery.release_summary:
        state["release_summary"] = discovery.release_summary
    if discovery.release_url:
        state["release_url"] = discovery.release_url
    custom_state = discovery.provider.hass_state_format(discovery)
    if custom_state:
        state.update(custom_state)
    invalid_keys = [k for k in state if k not in HASS_UPDATE_SCHEMA]
    if invalid_keys:
        log.warning(f"Invalid keys in state: {invalid_keys}")
        state = {k: v for k, v in state.items() if k in HASS_UPDATE_SCHEMA}
    return state
