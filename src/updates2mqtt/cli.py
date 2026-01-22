import structlog
from omegaconf import OmegaConf

from updates2mqtt.config import DockerConfig, NodeConfig
from updates2mqtt.integrations.docker import DockerProvider
from updates2mqtt.model import Discovery

log = structlog.get_logger()

"""
Super simple CLI

python updates2mqtt.cli container=frigate

python updates2mqtt.cli container=frigate registry_access=docker_client
"""


def run_once_docker() -> None:
    # will be a cli someday
    cli_conf = OmegaConf.from_cli()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger("DEBUG"))

    docker_scanner = DockerProvider(DockerConfig(registry_access=cli_conf.get("registry_access", "OCI_V2")), NodeConfig(), None)
    discovery = docker_scanner.rescan(Discovery(docker_scanner, cli_conf.get("container", "frigate"), "cli", "manual"))
    if discovery:
        log.info(discovery.as_dict())


if __name__ == "__main__":
    run_once_docker()
