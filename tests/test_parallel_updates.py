"""Updates running concurrently on the event loop, and recreating this app's own container"""

import asyncio
import sys
import time
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import docker.errors
import pytest
from docker import DockerClient

import updates2mqtt.integrations.docker as mut
from tests.lib_test import docker_config
from updates2mqtt.config import NodeConfig
from updates2mqtt.helpers import run_process
from updates2mqtt.integrations.docker_enrich import DockerImageInfo, DockerServiceDetails
from updates2mqtt.model import Discovery

SELF_REF = "ghcr.io/rhizomatics/updates2mqtt:latest"


def provider(mock_docker_client: DockerClient, **kwargs: Any) -> mut.DockerProvider:
    with patch("docker.from_env", return_value=mock_docker_client):
        return mut.DockerProvider(docker_config(discover_metadata={}, **kwargs), NodeConfig(), self_bounce=Event())


def add_discovery(uut: mut.DockerProvider, name: str, ref: str = "nginx:latest", **service: Any) -> Discovery:
    discovery = Discovery(
        uut,
        name,
        "test-session",
        "node001",
        can_pull=True,
        current_detail=DockerImageInfo(ref),
        installation_detail=DockerServiceDetails(**service),
    )
    uut.discoveries[name] = discovery
    return discovery


class ConcurrencyProbe:
    """Stand in for an update, recording how many ran at once"""

    def __init__(self, duration: float = 0.2) -> None:
        self.duration = duration
        self.running = 0
        self.max_running = 0

    async def __call__(self, *_args: Any, **_kwargs: Any) -> bool:
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        await asyncio.sleep(self.duration)
        self.running -= 1
        return True


# === concurrency ===


async def test_commands_run_in_parallel_up_to_limit(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, max_concurrent_updates=2)
    for name in ("a", "b", "c", "d"):
        add_discovery(uut, name)
    probe = ConcurrencyProbe()
    with patch.object(uut, "update", new=probe), patch.object(uut, "rescan", return_value=None):
        started: float = time.monotonic()
        await asyncio.gather(*(uut.command(name, "install", Mock(), Mock()) for name in ("a", "b", "c", "d")))
        elapsed: float = time.monotonic() - started

    assert probe.max_running == 2
    # two batches of two, rather than four in sequence
    assert elapsed < probe.duration * 3
    assert uut.active_updates == set()


async def test_queued_command_shown_in_progress_before_slot_free(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client, max_concurrent_updates=1)
    add_discovery(uut, "a")
    add_discovery(uut, "b")
    on_start = Mock()
    with patch.object(uut, "update", new=ConcurrencyProbe(0.2)), patch.object(uut, "rescan", return_value=None):
        first = asyncio.create_task(uut.command("a", "install", on_start, Mock()))
        second = asyncio.create_task(uut.command("b", "install", on_start, Mock()))
        await asyncio.sleep(0.05)
        assert on_start.call_count == 2
        assert uut.active_updates == {"a", "b"}
        await asyncio.gather(first, second)


async def test_event_loop_not_blocked_by_compose(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    """A slow compose subprocess leaves the loop free for other work, e.g. heartbeats"""
    uut = provider(mock_docker_client)
    slow = [sys.executable, "-c", "import time; time.sleep(0.5)"]
    ticks: int = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    ticking = asyncio.create_task(ticker())
    with patch.object(uut, "compose_args", return_value=slow):
        assert await uut.execute_compose(mut.DockerComposeCommand.UP, [], None, str(tmp_path), uut.log)
    ticking.cancel()
    assert ticks >= 5


async def test_restarts_serialized_within_compose_project(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    same_a = add_discovery(uut, "a", compose_path=str(tmp_path), compose_project="proj", compose_service="a")
    same_b = add_discovery(uut, "b", compose_path=str(tmp_path), compose_project="proj", compose_service="b")
    probe = ConcurrencyProbe(0.1)
    with patch.object(uut, "execute_compose", new=probe):
        await asyncio.gather(uut.restart(same_a), uut.restart(same_b))
    assert probe.max_running == 1


async def test_restarts_parallel_across_compose_projects(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    one = add_discovery(uut, "a", compose_path=str(tmp_path), compose_project="one")
    two = add_discovery(uut, "b", compose_path=str(tmp_path), compose_project="two")
    probe = ConcurrencyProbe(0.1)
    with patch.object(uut, "execute_compose", new=probe):
        await asyncio.gather(uut.restart(one), uut.restart(two))
    assert probe.max_running == 2


def test_max_concurrent_updates_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert docker_config().max_concurrent_updates == 3
    monkeypatch.setenv("U2M_MAX_CONCURRENT_UPDATES", "5")
    assert docker_config().max_concurrent_updates == 5


@pytest.mark.parametrize(("configured", "expected"), [(1, 1), (6, 6), (0, 1), (-2, 1)])
def test_max_concurrent_updates_slots(mock_docker_client: DockerClient, configured: int, expected: int) -> None:
    assert provider(mock_docker_client, max_concurrent_updates=configured).max_concurrent_updates() == expected


# === self-bounce ===


@pytest.fixture
def no_bounce_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mut, "SELF_BOUNCE_DELAY", 0)
    monkeypatch.setattr(mut, "SELF_BOUNCE_DRAIN_INTERVAL", 0.01)
    monkeypatch.setattr(mut, "RECREATE_WAIT_INTERVAL", 0.01)


async def test_self_restart_deferred_to_background(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    me = add_discovery(uut, "u2m", ref=SELF_REF, compose_path=str(tmp_path), compose_service="u2m")
    with (
        patch.object(uut, "execute_compose") as mock_compose,
        patch.object(uut, "self_bounce_recreate", new=AsyncMock()) as mock_recreate,
    ):
        assert await uut.restart(me)
        assert uut.self_bounce is not None and uut.self_bounce.is_set()
        await asyncio.sleep(0)
        mock_recreate.assert_awaited_once()
    mock_compose.assert_not_called()


async def test_self_bounce_uses_helper_container(
    mock_docker_client: DockerClient, tmp_path: Path, no_bounce_delay: None
) -> None:
    uut = provider(mock_docker_client)
    assert uut.self_bounce is not None
    uut.self_bounce.set()
    service = DockerServiceDetails(compose_path=str(tmp_path), compose_service="u2m")
    recreate = AsyncMock(return_value=True)
    helper = Mock()
    with (
        patch.object(uut, "launch_self_bounce_helper", return_value=helper) as mock_launch,
        patch.object(uut, "wait_for_self_bounce_helper", new=AsyncMock()) as mock_wait,
    ):
        await uut.self_bounce_recreate("u2m", service, recreate, via_portainer=False)
    mock_launch.assert_called_once()
    mock_wait.assert_awaited_once_with(helper, mock_launch.call_args.args[1])
    recreate.assert_not_awaited()
    # still running once the helper has finished, so the bounce didn't happen
    assert not uut.self_bounce.is_set()


async def test_self_bounce_falls_back_to_in_process(
    mock_docker_client: DockerClient, tmp_path: Path, no_bounce_delay: None
) -> None:
    uut = provider(mock_docker_client)
    assert uut.self_bounce is not None
    uut.self_bounce.set()
    service = DockerServiceDetails(compose_path=str(tmp_path), compose_service="u2m")
    recreate = AsyncMock(return_value=True)
    with patch.object(uut, "launch_self_bounce_helper", return_value=None):
        await uut.self_bounce_recreate("u2m", service, recreate, via_portainer=False)
    recreate.assert_awaited_once()
    assert uut.self_bounce.is_set()


async def test_self_bounce_via_portainer(mock_docker_client: DockerClient, no_bounce_delay: None) -> None:
    uut = provider(mock_docker_client)
    recreate = AsyncMock(return_value=False)
    assert uut.self_bounce is not None
    uut.self_bounce.set()
    with patch.object(uut, "launch_self_bounce_helper") as mock_launch:
        await uut.self_bounce_recreate("u2m", DockerServiceDetails(), recreate, via_portainer=True)
    recreate.assert_awaited_once()
    mock_launch.assert_not_called()
    # failed redeploy leaves this instance accepting commands again
    assert not uut.self_bounce.is_set()


async def test_self_bounce_waits_for_other_updates(mock_docker_client: DockerClient, no_bounce_delay: None) -> None:
    uut = provider(mock_docker_client)
    uut.active_updates.update({"u2m", "other"})
    recreate = AsyncMock(return_value=True)
    with patch.object(uut, "launch_self_bounce_helper", return_value=None):
        bounce = asyncio.create_task(uut.self_bounce_recreate("u2m", DockerServiceDetails(), recreate, False))
        await asyncio.sleep(0.1)
        recreate.assert_not_awaited()
        uut.active_updates.discard("other")
        await bounce
    recreate.assert_awaited_once()


async def test_self_bounce_drain_times_out(
    mock_docker_client: DockerClient, no_bounce_delay: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mut, "SELF_BOUNCE_DRAIN_TIMEOUT", 0.05)
    uut = provider(mock_docker_client)
    uut.active_updates.add("stuck")
    recreate = AsyncMock(return_value=True)
    with patch.object(uut, "launch_self_bounce_helper", return_value=None):
        await asyncio.wait_for(uut.self_bounce_recreate("u2m", DockerServiceDetails(), recreate, False), timeout=2)
    recreate.assert_awaited_once()


async def test_commands_refused_while_self_bounce_pending(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    add_discovery(uut, "a")
    assert uut.self_bounce is not None
    uut.self_bounce.set()
    on_start = Mock()
    with patch.object(uut, "update") as mock_update:
        assert not await uut.command("a", "install", on_start, Mock())
    mock_update.assert_not_called()
    on_start.assert_not_called()


def own_container_mock() -> Mock:
    own = Mock()
    own.id = "f" * 64
    own.name = "updates2mqtt"
    own.attrs = {
        "Image": "sha256:current",
        "Config": {"User": "1000"},
        "HostConfig": {"NetworkMode": "infra_default", "GroupAdd": ["998"]},
    }
    return own


def test_launch_self_bounce_helper(mock_docker_client: DockerClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the shell, or the session-wide integration fixtures, may have set any of these
    for var in mut.DOCKER_CLIENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://socket-proxy:2375")
    uut = provider(mock_docker_client)
    service = DockerServiceDetails(compose_path=str(tmp_path), compose_service="u2m", compose_project="infra")
    with patch.object(uut, "own_container", return_value=own_container_mock()):
        assert uut.launch_self_bounce_helper(service, uut.log) is not None

    kwargs: dict[str, Any] = mock_docker_client.containers.run.call_args.kwargs  # type: ignore[attr-defined]
    assert mock_docker_client.containers.run.call_args.args == ("sha256:current",)  # type: ignore[attr-defined]
    assert kwargs["entrypoint"] == ["docker"]
    assert kwargs["command"] == ["compose", "-p", "infra", "up", "--detach", "--yes", "u2m"]
    assert kwargs["working_dir"] == str(tmp_path)
    assert kwargs["volumes_from"] == ["f" * 64]
    assert kwargs["environment"] == {"DOCKER_HOST": "tcp://socket-proxy:2375"}
    assert kwargs["network_mode"] == "infra_default"
    assert kwargs["user"] == "1000"
    assert kwargs["group_add"] == ["998"]
    assert kwargs["labels"][mut.SELF_BOUNCE_HELPER_LABEL] == "updates2mqtt"
    assert kwargs["labels"]["updates2mqtt.ignore"] == "true"
    assert kwargs["detach"] is True


def test_launch_self_bounce_helper_needs_own_container(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    with patch.object(uut, "own_container", return_value=None):
        assert uut.launch_self_bounce_helper(DockerServiceDetails(compose_path=str(tmp_path)), uut.log) is None
    mock_docker_client.containers.run.assert_not_called()  # type: ignore[attr-defined]


def test_launch_self_bounce_helper_needs_compose_path(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    with patch.object(uut, "own_container", return_value=own_container_mock()):
        assert uut.launch_self_bounce_helper(DockerServiceDetails(compose_path="/not/here"), uut.log) is None
    mock_docker_client.containers.run.assert_not_called()  # type: ignore[attr-defined]


def test_launch_self_bounce_helper_api_error(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    mock_docker_client.containers.run.side_effect = docker.errors.APIError("no")  # type: ignore[attr-defined]
    with patch.object(uut, "own_container", return_value=own_container_mock()):
        assert uut.launch_self_bounce_helper(DockerServiceDetails(compose_path=str(tmp_path)), uut.log) is None


async def test_wait_for_self_bounce_helper_reports_exit(mock_docker_client: DockerClient, no_bounce_delay: None) -> None:
    uut = provider(mock_docker_client)
    helper = MagicMock()
    helper.status = "exited"
    helper.attrs = {"State": {"ExitCode": 1}}
    helper.logs.return_value = b"compose error"
    await uut.wait_for_self_bounce_helper(helper, uut.log)
    helper.remove.assert_called_once()


def test_clean_self_bounce_helpers_on_initialize(mock_docker_client: DockerClient) -> None:
    uut = provider(mock_docker_client)
    leftover = MagicMock()
    leftover.attrs = {"State": {"ExitCode": 0}}
    leftover.logs.return_value = b""
    mock_docker_client.containers.list.return_value = [leftover]  # type: ignore[attr-defined]
    uut.clean_self_bounce_helpers()
    mock_docker_client.containers.list.assert_called_with(  # type: ignore[attr-defined]
        all=True, filters={"label": mut.SELF_BOUNCE_HELPER_LABEL, "status": "exited"}
    )
    leftover.remove.assert_called_once()


def test_own_container_from_mountinfo(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    uut = provider(mock_docker_client)
    container_id: str = "a1" * 32
    mountinfo: str = f"1 2 0:1 /var/lib/docker/containers/{container_id}/hostname /etc/hostname rw - ext4 /dev/sda rw\n"
    own = Mock()
    mock_docker_client.containers.get.side_effect = lambda c: own if c == container_id else None  # type: ignore[attr-defined]
    with patch.object(Path, "read_text", return_value=mountinfo), patch.object(Path, "exists", return_value=False):
        assert uut.own_container() is own


# === run_process ===


async def test_run_process_success() -> None:
    result = await run_process([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"])
    assert result.ok
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


async def test_run_process_failure() -> None:
    result = await run_process([sys.executable, "-c", "raise SystemExit(3)"])
    assert not result.ok
    assert result.returncode == 3


async def test_run_process_missing_executable() -> None:
    result = await run_process(["/no/such/executable"])
    assert result.returncode is None
    assert not result.ok


async def test_run_process_timeout() -> None:
    started: float = time.monotonic()
    result = await run_process([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.2)
    assert result.returncode is None
    assert time.monotonic() - started < 5


async def test_run_process_cancelled_kills_process() -> None:
    task = asyncio.create_task(run_process([sys.executable, "-c", "import time; time.sleep(10)"]))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)


# === compose recreate ===


@pytest.mark.parametrize(
    ("name", "expected"),
    [("5c94ff38a05b_updates2mqtt", True), ("updates2mqtt", False), ("aaaaaaaaaaaa_other", False), (None, False)],
)
def test_is_compose_recreate_name(name: str | None, expected: bool) -> None:
    container = Mock(id="5c94ff38a05b" + "0" * 52)
    container.name = name
    assert mut.is_compose_recreate_name(container) is expected
