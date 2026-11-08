"""Docker enrichment edge paths: malformed digests and listings, unusable references, registry errors"""

from unittest.mock import Mock

import docker.errors
from pytest_httpx import HTTPXMock

from tests.lib_test import docker_config
from updates2mqtt.config import MetadataSourceConfig, RegistryConfig
from updates2mqtt.helpers import Throttler
from updates2mqtt.integrations.docker_enrich import (
    HOTIO_SITE_TREE_URL,
    ContainerDistributionAPIVersionLookup,
    DockerClientVersionLookup,
    DockerImageInfo,
    DockerServiceDetails,
    HotioPackageEnricher,
    cherrypick_annotations,
)


def test_condense_digest_tolerates_garbage() -> None:
    info = DockerImageInfo("nginx")
    assert info.condense_digest(12345) is None  # type: ignore[arg-type]


def test_service_details_include_git_fields() -> None:
    details = DockerServiceDetails(compose_path="/compose", git_repo_path="repo")
    details.git_local_timestamp = "2024-01-01T00:00:00"
    result = details.as_dict()
    assert result["git_repo_path"] == "repo"
    assert result["git_local_timestamp"] == "2024-01-01T00:00:00"


UBUNTU_BASE_ANNOTATIONS = {"org.opencontainers.image.ref.name": "ubuntu", "org.opencontainers.image.version": "24.04"}


def test_ubuntu_base_version_not_taken_as_image_version() -> None:
    # as seen with greptime/greptimedb, built on an ubuntu base image
    local = DockerImageInfo("greptime/greptimedb:latest", annotations=UBUNTU_BASE_ANNOTATIONS)
    assert "image_version" not in cherrypick_annotations(local, None)
    assert cherrypick_annotations(local, None)["ref_name"] == "ubuntu"


def test_ubuntu_own_version_kept() -> None:
    for ref in ("ubuntu:24.04", "docker.io/library/ubuntu:24.04"):
        local = DockerImageInfo(ref, annotations=UBUNTU_BASE_ANNOTATIONS)
        assert cherrypick_annotations(local, None)["image_version"] == "24.04"


def test_hotio_enricher_unparseable_listing(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, content=b"not json", headers={"content-type": "application/json"})
    uut = HotioPackageEnricher(docker_config(discover_metadata={"hotio.dev": MetadataSourceConfig(cache_ttl=0)}))
    uut.initialize()
    assert uut.containers == set()


def test_registry_lookup_needs_name_and_index() -> None:
    uut = ContainerDistributionAPIVersionLookup(Throttler(), RegistryConfig(), transport=Mock())
    local = DockerImageInfo("nginx")
    local.index_name = None
    assert uut.lookup(local).short_digest is None


def test_registry_lookup_invalid_reference() -> None:
    uut = ContainerDistributionAPIVersionLookup(Throttler(), RegistryConfig(), transport=Mock())
    local = DockerImageInfo("nginx:latest")
    local.name = "UPPER/Case"
    result = uut.lookup(local)
    assert result.error is not None
    assert not result.throttled


def test_docker_client_lookup_retries_server_errors() -> None:
    client = Mock()
    error = docker.errors.APIError("boom", response=Mock(status_code=500))
    client.images.get_registry_data.side_effect = error
    uut = DockerClientVersionLookup(client, Throttler(), RegistryConfig())
    result = uut.lookup(DockerImageInfo("nginx:latest"), retries=2)
    assert client.images.get_registry_data.call_count == 2
    assert result.error is not None
    assert not result.throttled


def test_docker_client_lookup_gives_up_on_client_error() -> None:
    client = Mock()
    client.images.get_registry_data.side_effect = docker.errors.APIError("nope", response=Mock(status_code=404))
    uut = DockerClientVersionLookup(client, Throttler(), RegistryConfig())
    result = uut.lookup(DockerImageInfo("nginx:latest"), retries=3)
    assert result.error is not None
