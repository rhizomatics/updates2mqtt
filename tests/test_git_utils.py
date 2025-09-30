import datetime
from pathlib import Path

from pytest_subprocess import FakeProcess  # type: ignore[import-not-found]

from updates2mqtt.integrations.git_utils import git_check_update_available, git_pull, git_timestamp, git_trust


def test_git_timestamp(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="""2024-04-12T00:16:33+01:00""")
    assert git_timestamp(Path("/my/path")) == datetime.datetime(
        2024,
        4,
        12,
        0,
        16,
        33,
        0,
        datetime.timezone(offset=datetime.timedelta(hours=1)),
    )


def test_git_trust(fake_process: FakeProcess) -> None:
    fake_process.register("git config --global --add safe.directory /my/path", returncode=0)
    assert git_trust(Path("/my/path"))


def test_git_pull(fake_process: FakeProcess) -> None:
    fake_process.register("git pull", returncode=0)
    assert git_pull(Path("/my/path"))
    fake_process.register("git pull", returncode=23)
    assert git_pull(Path("/my/path")) is False


def test_git_check_update_available(fake_process: FakeProcess) -> None:
    fake_process.register(
        "git fetch;git status -uno", stdout="Your branch is behind 'origin/main' by 1 commit, and can be fast-forwarded.", returncode=0
    )
    assert git_check_update_available(Path("/my/path"))
    fake_process.register("git fetch;git status -uno", stdout="Your branch is up to date with 'origin/main'.", returncode=0)
    assert git_check_update_available(Path("/my/path")) is False
    fake_process.register("git fetch;git status -uno", returncode=1)
    assert git_check_update_available(Path("/my/path"), timeout=5) is False
