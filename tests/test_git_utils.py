from pathlib import Path

from pytest_subprocess import FakeProcess

from updates2mqtt.integrations.git_utils import (
    GIT_HARDENING,
    git_check_update_available,
    git_command,
    git_iso_timestamp,
    git_local_digest,
    git_pull,
    git_repo_allowed,
)

GIT_EXEC = Path("/usr/bin/git")
REPO = Path("/my/path")


def git(*args: str) -> list[str]:
    return git_command(GIT_EXEC, REPO, *args)


def test_git_iso_timestamp(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="""2024-04-12T00:16:33+01:00""")
    assert git_iso_timestamp(Path("/my/path"), GIT_EXEC) == "2024-04-12T00:16:33+01:00"


async def test_git_pull(fake_process: FakeProcess) -> None:
    fake_process.register(git("pull"), returncode=0)
    assert await git_pull(Path("/my/path"), GIT_EXEC)
    fake_process.register(git("pull"), returncode=23)
    assert await git_pull(Path("/my/path"), GIT_EXEC) is False


def test_git_check_update_available(fake_process: FakeProcess) -> None:
    fake_process.register(git("fetch"), returncode=0)
    fake_process.register(
        git("status", "-uno"),
        stdout="""On branch main\nYour branch is behind \'origin/main\' by 1 commit, and can be fast-forwarded.\n  (use "git pull" to update your local branch)\n\nnothing to commit (use -u to show untracked files)""",
        returncode=0,
    )
    assert git_check_update_available(Path("/my/path"), GIT_EXEC) == 1
    # status is still used when the fetch fails, e.g. offline
    fake_process.register(git("fetch"), returncode=1)
    fake_process.register(git("status", "-uno"), stdout="Your branch is up to date with 'origin/main'.", returncode=0)
    assert git_check_update_available(Path("/my/path"), GIT_EXEC) == 0
    fake_process.register(git("fetch"), returncode=0)
    fake_process.register(git("status", "-uno"), returncode=1)
    assert git_check_update_available(Path("/my/path"), GIT_EXEC, timeout=5) == 0


def test_git_local_digest(fake_process: FakeProcess) -> None:
    # Test successful case - returns git:{hash} truncated to 19 chars total
    fake_process.register(
        git("rev-parse", "HEAD"),
        stdout="abc123def456789012345678901234567890",
        returncode=0,
    )
    assert git_local_digest(Path("/my/path"), GIT_EXEC) == "abc123def456789"


def test_git_local_digest_failure(fake_process: FakeProcess) -> None:
    # Test failure case - returns None
    fake_process.register(git("rev-parse", "HEAD"), returncode=128)
    assert git_local_digest(Path("/my/path"), GIT_EXEC) is None


def test_git_iso_timestamp_git_failure(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], returncode=128)
    assert git_iso_timestamp(Path("/my/path"), GIT_EXEC) is None


def test_git_iso_timestamp_unparseable(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="not a date")
    assert git_iso_timestamp(Path("/my/path"), GIT_EXEC) is None


def test_git_local_digest_unexpected_error(fake_process: FakeProcess) -> None:
    def explode(process: object) -> None:
        raise OSError("no git")

    fake_process.register(git("rev-parse", "HEAD"), callback=explode)
    assert git_local_digest(Path("/my/path"), GIT_EXEC) is None


def test_git_command_is_an_argument_list_with_hardening() -> None:
    cmd = git_command(GIT_EXEC, Path("/my/x;touch pwned;"), "log", "-1")
    # one argument however the path is spelt, so nothing for a shell to interpret
    assert cmd[:3] == ["/usr/bin/git", "-c", f"safe.directory={Path('/my/x;touch pwned;').resolve()}"]
    assert cmd[-2:] == ["log", "-1"]
    for setting in GIT_HARDENING:
        assert setting in cmd
    assert "protocol.ext.allow=never" in cmd
    assert "core.fsmonitor=false" in cmd


def test_git_commands_run_without_a_shell(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="2024-04-12T00:16:33+01:00")
    git_iso_timestamp(REPO, GIT_EXEC)
    git_local_digest(REPO, GIT_EXEC)
    git_check_update_available(REPO, GIT_EXEC)
    assert fake_process.calls
    for call in fake_process.calls:
        assert isinstance(call, list)
        assert "safe.directory=" in call[2]


def test_git_repo_allowed(tmp_path: Path) -> None:
    root = tmp_path / "containers"
    (root / "app" / "src").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    # no roots configured, anything set on the container is accepted
    assert git_repo_allowed(tmp_path / "elsewhere", [])
    assert git_repo_allowed(tmp_path / "elsewhere", None)
    assert git_repo_allowed(root / "app" / "src", [str(root)])
    assert git_repo_allowed(root, [str(root)])
    assert not git_repo_allowed(tmp_path / "elsewhere", [str(root)])
    # no climbing back out of a root
    assert not git_repo_allowed(root / "app" / ".." / ".." / "elsewhere", [str(root)])
    assert git_repo_allowed(tmp_path / "elsewhere", [str(root), str(tmp_path / "elsewhere")])
