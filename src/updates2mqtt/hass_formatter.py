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
    discovery: Discovery,
    object_id: str,
    state_topic: str,
    command_topic: str | None,
    force_command_topic: bool | None,
    device_creation: bool = True,
    area: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": discovery.title,
        "device_class": None,  # not firmware, so defaults to null
        "unique_id": object_id,
        "state_topic": state_topic,
        "source_session": session,
        "supported_features": discovery.features,
        "can_update": discovery.can_update,
        "can_build": discovery.can_build,
        "can_restart": discovery.can_restart,
        "update_policy": discovery.update_policy,
        "origin": {
            "name": f"{discovery.node} updates2mqtt",
            "sw_version": updates2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "support_url": "https://github.com/rhizomatics/updates2mqtt/issues",
        },
    }
    if discovery.entity_picture_url:
        config["entity_picture"] = discovery.entity_picture_url
    if discovery.device_icon:
        config["icon"] = discovery.device_icon
    if device_creation:
        config["device"] = {
            "name": f"{discovery.node} updates2mqtt",
            "sw_version": updates2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
            "manufacturer": "rhizomatics",
            "identifiers": [f"{discovery.node}.updates2mqtt"],
        }
        if area:
            config["device"]["suggested_area"] = area
    if command_topic and (discovery.can_update or force_command_topic):
        config["command_topic"] = command_topic
        if discovery.can_update:
            config["payload_install"] = f"{discovery.source_type}|{discovery.name}|install"
    if discovery.custom.get("git_repo_path"):
        config["git_repo_path"] = discovery.custom["git_repo_path"]
    config.update(discovery.provider.hass_config_format(discovery))
    return config


def hass_format_state(discovery: Discovery, session: str, in_progress: bool = False) -> dict[str, Any]:  # noqa: ARG001
    state = {
        "installed_version": discovery.current_version,
        "latest_version": discovery.latest_version,
        "title": discovery.title,
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
