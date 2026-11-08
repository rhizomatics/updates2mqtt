"""Docker provider edge paths: failures from the Docker API, analysis rules and self-bounce recovery"""

import asyncio
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import docker.errors
import pytest
from docker import DockerClient
from docker.models.containers import Container
from pytest_subprocess import FakeProcess

import updates2mqtt.integrations.docker as mut
from tests.lib_test import build_mock_container, docker_config
from updates2mqtt.config import (
    GitHubConfig,
    NodeConfig,
    PublishPolicy,
    RegistryAPI,
    RegistryConfig,
    Selector,
    UpdatePolicy,
    VersionPolicy,
)
from updates2mqtt.integrations.docker import ContainerCustomization, DockerComposeCommand
from updates2mqtt.integrations.docker_enrich import DockerImageInfo, DockerServiceDetails
from updates2mqtt.model import Discovery


def provider(mock_docker_client: DockerClient, api: RegistryAPI = RegistryAPI.DISABLED, **kwargs: Any) -> mut.DockerProvider:
    """Registry lookups disabled unless asked for, so no network calls"""
    with patch("docker.from_env", return_value=mock_docker_client):
        return mut.DockerProvider(
            docker_config(discover_metadata={}, registry=RegistryConfig(api=api), **kwargs),
            NodeConfig(),
            self_bounce=Event(),
        )


def discovery_for(uut: mut.DockerProvider, name: str = "app", **kwargs: Any) -> Discovery:
    return Discovery(uut, name, "test-session", "node001", **kwargs)


@pytest.fixture
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mut, "SELF_BOUNCE_DELAY", 0)
    monkeypatch.setattr(mut, "RECREATE_WAIT_INTERVAL", 0.01)


def test_safe_json_dt() -> None:
    assert mut.safe_json_dt(None) is None
    assert mut.safe_json_dt(0) is None
    assert mut.safe_json_dt(86400) == "1970-01-02T00:00:00.0000"


def test_container_customization_version_policy_and_no_env() -> None:
    container = Mock(spec=Container)
    container.name = "app"
    container.labels = {"updates2mqtt.version_policy": "digest", "updates2mqtt.update": "auto"}
    container.attrs = {"Config": {"Env": None}}
    uut = ContainerCustomization(container)
    assert uut.version_policy == VersionPolicy.DIGEST
    assert uut.update == UpdatePolicy.AUTO


# === construction and setup ===


def test_portainer_missing_ca_certs_still_enabled(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        cfg = docker_config(discover_metadata={})
        cfg.portainer.url = "https://portainer.test"
        cfg.portainer.api_key = "key"
        cfg.portainer.ca_certs = str(tmp_path / "missing.pem")
        uut = mut.DockerProvider(cfg, NodeConfig(), github_cfg=GitHubConfig())
    assert uut.portainer is not None
    assert uut.github_enricher is not None


def test_initialize_runs_enrichers(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    uut.pkg_enrichers = [Mock(), Mock()]
    mock_docker_client.containers.list.return_value = []  # type: ignore[attr-defined]
    uut.initialize()
    for enricher in uut.pkg_enrichers:
        enricher.initialize.assert_called_once()  # type: ignore[attr-defined]


def test_max_concurrent_updates_invalid(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    uut.cfg = Mock(max_concurrent_updates="lots")
    assert uut.max_concurrent_updates() == mut.DEFAULT_MAX_CONCURRENT_UPDATES


def test_default_metadata_needs_an_enricher(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    uut.pkg_enrichers = []
    with pytest.raises(ValueError, match="No enricher"):
        uut.default_metadata(DockerImageInfo("nginx"))


# === updating ===


async def test_update_records_repeat_attempt(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    discovery = discovery_for(uut)
    discovery.update_last_attempt = 1.0
    mock_docker_client.containers.get.side_effect = docker.errors.APIError("gone")  # type: ignore[attr-defined]
    with (
        patch.object(uut, "fetch", new=AsyncMock(return_value=None)),
        patch.object(uut, "restart", new=AsyncMock(return_value=False)),
    ):
        assert not await uut.update(discovery)
    assert discovery.update_last_attempt > 1.0


async def test_fetch_pull_failure(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    mock_docker_client.images.pull.return_value = None  # type: ignore[attr-defined]
    discovery = discovery_for(uut, can_pull=True, current_detail=DockerImageInfo("nginx:latest"))
    assert await uut.fetch(discovery) is None


def test_full_repo_path(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    with pytest.raises(ValueError, match="null paths"):
        uut.full_repo_path(None, "repo")
    assert uut.full_repo_path("/compose", "/abs/repo") == Path("/abs/repo")
    assert uut.full_repo_path("/compose", "repo") == Path("/compose/repo")


async def test_build_needs_compose_path(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    assert not await uut.build(discovery_for(uut))
    assert not await uut.build(discovery_for(uut, installation_detail=DockerServiceDetails()))


async def test_execute_compose_skips_invisible_path(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    assert not await uut.execute_compose(DockerComposeCommand.UP, [], "svc", "/not/visible", uut.log)
    assert not await uut.execute_compose(DockerComposeCommand.UP, [], "svc", None, uut.log)


async def test_execute_compose_detects_v1(mock_docker_client: DockerClient, tmp_path: Path, fake_process: FakeProcess) -> None:
    uut = provider(mock_docker_client)
    fake_process.register(["docker", "compose", "up", "svc"], returncode=1, stderr="'compose' is not a docker command")
    assert not await uut.execute_compose(DockerComposeCommand.UP, [], "svc", str(tmp_path), uut.log)
    assert uut.cfg.compose_version == "v1"
    assert uut.compose_args(DockerComposeCommand.UP, [], "svc")[0] == "docker-compose"


async def test_restart_needs_service_info(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    assert not await uut.restart(discovery_for(uut))


def test_container_image_id_api_error(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    mock_docker_client.containers.get.side_effect = docker.errors.APIError("down")  # type: ignore[attr-defined]
    assert uut.container_image_id("app") is None


# === self-bounce recovery ===


async def test_self_bounce_recovers_from_failure(mock_docker_client: DockerClient, no_waits: None) -> None:
    uut = provider(mock_docker_client)
    assert uut.self_bounce is not None
    uut.self_bounce.set()
    recreate = AsyncMock(side_effect=RuntimeError("redeploy failed"))
    await uut.self_bounce_recreate("u2m", DockerServiceDetails(), recreate, via_portainer=True)
    assert not uut.self_bounce.is_set()


async def test_self_bounce_cancel_propagates(mock_docker_client: DockerClient, no_waits: None) -> None:
    uut = provider(mock_docker_client)
    recreate = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await uut.self_bounce_recreate("u2m", DockerServiceDetails(), recreate, via_portainer=True)


def test_own_container_from_hostname(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    own = Mock()
    mock_docker_client.containers.get.side_effect = lambda c: own if c == "myhost" else None  # type: ignore[attr-defined]
    with (
        patch.object(mut.Path, "read_text", side_effect=OSError("no proc")),
        patch.object(mut.Path, "exists", return_value=True),
        patch.object(mut.socket, "gethostname", return_value="myhost"),
    ):
        assert uut.own_container() is own


def test_own_container_unknown(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    mock_docker_client.containers.get.side_effect = docker.errors.NotFound("no")  # type: ignore[attr-defined]
    with (
        patch.object(mut.Path, "read_text", return_value=""),
        patch.object(mut.Path, "exists", return_value=True),
        patch.object(mut.socket, "gethostname", return_value="renamed"),
    ):
        assert uut.own_container() is None


def test_launch_self_bounce_helper_needs_image(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    own = Mock(id="f" * 64, attrs={"Config": {}})
    with patch.object(uut, "own_container", return_value=own):
        assert uut.launch_self_bounce_helper(DockerServiceDetails(compose_path=str(tmp_path)), uut.log) is None
    mock_docker_client.containers.run.assert_not_called()  # type: ignore[attr-defined]


async def test_wait_for_self_bounce_helper_removed(mock_docker_client: DockerClient, no_waits: None) -> None:
    uut = provider(mock_docker_client)
    helper = MagicMock()
    helper.reload.side_effect = docker.errors.NotFound("gone")
    with patch.object(uut, "report_self_bounce_helper") as mock_report:
        await uut.wait_for_self_bounce_helper(helper, uut.log)
    mock_report.assert_not_called()


async def test_wait_for_self_bounce_helper_polls_then_times_out(
    mock_docker_client: DockerClient, no_waits: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mut, "COMPOSE_TIMEOUT", 0.05)
    uut = provider(mock_docker_client)
    helper = MagicMock()
    helper.status = "running"
    with patch.object(uut, "report_self_bounce_helper") as mock_report:
        await uut.wait_for_self_bounce_helper(helper, uut.log)
    assert helper.reload.call_count >= 1
    mock_report.assert_not_called()


def test_report_self_bounce_helper_tolerates_api_errors(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    helper = MagicMock()
    helper.attrs = {"State": {"ExitCode": 0}}
    helper.logs.side_effect = docker.errors.APIError("no logs")
    helper.remove.side_effect = docker.errors.APIError("in use")
    uut.report_self_bounce_helper(helper)
    helper.remove.assert_called_once()


def test_clean_self_bounce_helpers_api_error(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    mock_docker_client.containers.list.side_effect = docker.errors.APIError("down")  # type: ignore[attr-defined]
    with patch.object(uut, "report_self_bounce_helper") as mock_report:
        uut.clean_self_bounce_helpers()
    mock_report.assert_not_called()


# === rescan ===


async def test_rescan_ignores_throttled_result(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    discovery = discovery_for(uut)
    mock_docker_client.containers.get.return_value = Mock()  # type: ignore[attr-defined]
    throttled = discovery_for(uut, throttled=True)
    with patch.object(uut, "analyze", return_value=throttled):
        assert await uut.rescan(discovery) is None
    assert "app" not in uut.discoveries


# === analysis ===


def test_analyze_rejects_incomplete_containers(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    no_attrs = build_mock_container("nginx:latest")
    no_attrs.attrs = {}
    assert uut.analyze(no_attrs, "s") is None
    no_name = build_mock_container("nginx:latest")
    no_name.name = None  # type: ignore[misc]
    assert uut.analyze(no_name, "s") is None
    ignored = build_mock_container("nginx:latest")
    ignored.labels["updates2mqtt.ignore"] = "true"
    assert uut.analyze(ignored, "s") is None


def test_analyze_customized_policies(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    container = build_mock_container("nginx:latest")
    container.labels["updates2mqtt.update"] = "auto"
    container.labels["updates2mqtt.version_policy"] = "digest"
    result = uut.analyze(container, "s")
    assert result is not None
    assert result.update_policy == UpdatePolicy.AUTO
    assert result.version_policy == VersionPolicy.DIGEST


def test_analyze_fixed_version_policy(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, version_policy=VersionPolicy.TIMESTAMP)
    result = uut.analyze(build_mock_container("nginx:latest"), "s")
    assert result is not None
    assert result.version_policy == VersionPolicy.TIMESTAMP


def test_analyze_pinned_image_skips_registry(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, api=RegistryAPI.OCI_V2)
    container = build_mock_container("nginx:latest")
    repo_digest: str = container.image.attrs["RepoDigests"][0].split("@", 1)[1]  # type: ignore[union-attr]
    container.image.tags = [f"nginx:latest@{repo_digest}"]  # type: ignore[misc,union-attr]
    container.attrs["Config"]["Image"] = f"nginx:latest@{repo_digest}"
    with patch.object(uut.registry_image_lookup, "lookup") as mock_lookup:
        result = uut.analyze(container, "s")
    assert result is not None
    mock_lookup.assert_not_called()


def test_analyze_minimal_registry_lookup(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, api=RegistryAPI.OCI_V2_MINIMAL)
    container = build_mock_container("nginx:latest")
    with patch.object(uut.registry_image_lookup, "lookup", side_effect=lambda info, **_kw: info.reuse()) as mock_lookup:
        assert uut.analyze(container, "s") is not None
    assert mock_lookup.call_args.kwargs["minimal"] is True


def test_analyze_registry_selection_suppresses_lookup(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, api=RegistryAPI.OCI_V2, registry_select=Selector(exclude=["docker.io"]))
    with patch.object(uut.registry_image_lookup, "lookup") as mock_lookup:
        assert uut.analyze(build_mock_container("nginx:latest"), "s") is not None
    mock_lookup.assert_not_called()


def test_analyze_github_enrichment(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, api=RegistryAPI.OCI_V2)
    uut.github_enricher = Mock()
    container = build_mock_container("nginx:latest")
    latest = DockerImageInfo("nginx:latest", image_digest="sha256:" + "c" * 64)
    release = Mock(source_platform=mut.SOURCE_PLATFORM_GITHUB)
    with (
        patch.object(uut.registry_image_lookup, "lookup", return_value=latest),
        patch.object(uut.release_enricher, "enrich", return_value=release),
    ):
        assert uut.analyze(container, "s") is not None
    uut.github_enricher.enrich.assert_called_once_with(latest, release)


def test_analyze_git_repo_without_compose_path(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, allow_pull=False)
    container = build_mock_container("nginx:latest")
    container.labels["updates2mqtt.git_repo_path"] = "repo"
    result = uut.analyze(container, "s")
    assert result is not None
    assert not result.can_build
    assert result.update_type == "Unavailable"


def test_analyze_warns_compose_path_not_visible(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    container = build_mock_container("nginx:latest")
    container.labels["com.docker.compose.project.working_dir"] = "/somewhere/not/mounted"
    result = uut.analyze(container, "s")
    assert result is not None
    assert not result.can_restart


def test_analyze_excluded_from_home_assistant(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, image_ref_select=Selector(exclude=["nginx"]))
    result = uut.analyze(build_mock_container("nginx:latest"), "s")
    assert result is not None
    assert result.publish_policy == PublishPolicy.MQTT


def test_analyze_failure_returns_none(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    with patch.object(uut.release_enricher, "enrich", side_effect=RuntimeError("bad metadata")):
        assert uut.analyze(build_mock_container("nginx:latest"), "s") is None


# === scanning ===


async def test_scan_skips_recreating_and_failed_containers(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    good = build_mock_container("nginx:latest", name="good")
    good.id = "1" * 64  # type: ignore[misc]
    recreating = build_mock_container("nginx:latest", name=f"{'2' * 12}_good")
    recreating.id = "2" * 64  # type: ignore[misc]
    failing = build_mock_container("nginx:latest", name="failing")
    failing.id = "3" * 64  # type: ignore[misc]
    failing.attrs = {}
    mock_docker_client.containers.list.return_value = [good, recreating, failing]  # type: ignore[attr-defined]
    results = [d async for d in uut.scan("s", shuffle=False)]
    assert [d.name for d in results] == ["good"]


async def test_scan_stops_when_provider_stopped(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    uut.stopped.set()
    assert [d async for d in uut.scan("s")] == []
