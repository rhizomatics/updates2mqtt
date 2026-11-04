import base64
import json
import os
import time
from email.utils import formatdate
from pathlib import Path
from typing import Any

import pytest
from pytest_subprocess import FakeProcess

from updates2mqtt.oci import (
    ChainedCredentials,
    Credentials,
    DockerConfigCredentials,
    StaticCredentials,
    parse_www_authenticate,
)
from updates2mqtt.oci.auth import config_key_registry, parse_retry_after, run_credential_helper

# === challenges ===


def test_parse_bearer_any_order() -> None:
    [challenge] = parse_www_authenticate(
        'Bearer scope="repository:a/b:pull",service="registry.docker.io",realm="https://auth.docker.io/token"'
    )
    assert challenge.scheme == "bearer"
    assert challenge.realm == "https://auth.docker.io/token"
    assert challenge.service == "registry.docker.io"
    assert challenge.scope == "repository:a/b:pull"


def test_parse_quoted_comma_and_escapes() -> None:
    [challenge] = parse_www_authenticate(
        'Bearer realm="https://auth.example/token",scope="repository:a:pull,push",error="insufficient_scope",x="q\\"t"'
    )
    assert challenge.scope == "repository:a:pull,push"
    assert challenge.params["error"] == "insufficient_scope"
    assert challenge.params["x"] == 'q"t'


def test_parse_without_scope_and_unquoted() -> None:
    [challenge] = parse_www_authenticate("Bearer realm=https://auth.example/token, service=svc")
    assert challenge.realm == "https://auth.example/token"
    assert challenge.service == "svc"
    assert challenge.scope is None


def test_parse_multiple_challenges() -> None:
    challenges = parse_www_authenticate('Basic realm="registry", Bearer realm="https://a/token",service="s"', "Negotiate")
    assert [c.scheme for c in challenges] == ["basic", "bearer", "negotiate"]
    assert challenges[1].service == "s"


def test_parse_case_insensitive() -> None:
    [challenge] = parse_www_authenticate('BEARER Realm="https://a/token"')
    assert challenge.scheme == "bearer"
    assert challenge.realm == "https://a/token"


def test_parse_garbage() -> None:
    assert parse_www_authenticate("", "   ") == []


def test_parse_retry_after() -> None:
    assert parse_retry_after("42") == 42
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    when = parse_retry_after(formatdate(time.time() + 120, usegmt=True))
    assert when is not None
    assert 100 < when <= 121


# === docker config ===


def b64(user: str, password: str) -> str:
    return base64.b64encode(f"{user}:{password}".encode()).decode()


def docker_config(tmp_path: Path, config: dict[str, Any], **kwargs: Any) -> DockerConfigCredentials:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return DockerConfigCredentials(path, **kwargs)


@pytest.mark.parametrize(
    ("key", "registry"),
    [
        ("https://index.docker.io/v1/", "docker.io"),
        ("index.docker.io", "docker.io"),
        ("ghcr.io", "ghcr.io"),
        ("https://registry.example:5000/v2/", "registry.example:5000"),
    ],
)
def test_config_key_registry(key: str, registry: str) -> None:
    assert config_key_registry(key) == registry


def test_auths_base64(tmp_path: Path) -> None:
    creds = docker_config(tmp_path, {"auths": {"https://index.docker.io/v1/": {"auth": b64("me", "pa:ss")}}})
    assert creds.get("docker.io") == Credentials("me", "pa:ss")
    assert creds.get("index.docker.io") == Credentials("me", "pa:ss")
    assert creds.get("ghcr.io") is None


def test_auths_fields_and_tokens(tmp_path: Path) -> None:
    creds = docker_config(
        tmp_path,
        {
            "auths": {
                "ghcr.io": {"username": "u", "password": "p"},
                "myacr.azurecr.io": {"auth": b64("00000000-0000-0000-0000-000000000000", ""), "identitytoken": "refresh"},
                "registry.example": {"registrytoken": "bearer-token"},
                "empty.example": {},
            }
        },
    )
    assert creds.get("ghcr.io") == Credentials("u", "p")
    found = creds.get("myacr.azurecr.io")
    assert found is not None
    assert found.identity_token == "refresh"
    assert creds.get("registry.example") == Credentials(registry_token="bearer-token")
    assert creds.get("empty.example") is None


def test_cred_helpers(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def runner(helper: str, server: str) -> dict[str, Any] | None:
        calls.append((helper, server))
        if helper == "gcloud":
            return {"ServerURL": server, "Username": "oauth2accesstoken", "Secret": "gcp"}
        if helper == "desktop" and server == "https://index.docker.io/v1/":
            return {"ServerURL": server, "Username": "<token>", "Secret": "identity"}
        return None

    creds = docker_config(
        tmp_path,
        {
            "credHelpers": {"europe-docker.pkg.dev": "gcloud"},
            "credsStore": "desktop",
            "auths": {"ghcr.io": {"auth": b64("u", "p")}},
        },
        helper_runner=runner,
    )
    assert creds.get("europe-docker.pkg.dev") == Credentials("oauth2accesstoken", "gcp")
    assert creds.get("docker.io") == Credentials(identity_token="identity")
    # store has none, so falls back to the auths entry
    assert creds.get("ghcr.io") == Credentials("u", "p")
    # helper results are cached
    creds.get("europe-docker.pkg.dev")
    assert calls.count(("gcloud", "europe-docker.pkg.dev")) == 1


def test_reloads_when_changed(tmp_path: Path) -> None:
    creds = docker_config(tmp_path, {"auths": {"ghcr.io": {"auth": b64("old", "p")}}})
    assert creds.get("ghcr.io") == Credentials("old", "p")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"auths": {"ghcr.io": {"auth": b64("new", "p")}}}))
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    assert creds.get("ghcr.io") == Credentials("new", "p")


def test_missing_or_invalid_config(tmp_path: Path) -> None:
    assert DockerConfigCredentials(tmp_path / "nope.json").get("ghcr.io") is None
    (tmp_path / "bad.json").write_text("{not json")
    assert DockerConfigCredentials(tmp_path / "bad.json").get("ghcr.io") is None


def test_docker_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"auths": {"ghcr.io": {"auth": b64("env", "p")}}}))
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    assert DockerConfigCredentials().get("ghcr.io") == Credentials("env", "p")


def test_run_credential_helper(fake_process: FakeProcess) -> None:
    fake_process.register(
        ["docker-credential-pass", "get"], stdout=json.dumps({"Username": "u", "Secret": "s", "ServerURL": "ghcr.io"})
    )
    assert run_credential_helper("pass", "ghcr.io") == {"Username": "u", "Secret": "s", "ServerURL": "ghcr.io"}
    fake_process.register(["docker-credential-pass", "get"], returncode=1, stdout="credentials not found")
    assert run_credential_helper("pass", "ghcr.io") is None
    fake_process.register(["docker-credential-pass", "get"], stdout="not json")
    assert run_credential_helper("pass", "ghcr.io") is None


def test_run_credential_helper_missing() -> None:
    assert run_credential_helper("definitely-not-installed-helper", "ghcr.io") is None


def test_static_and_chained() -> None:
    static = StaticCredentials({"index.docker.io": Credentials("a", "b")})
    assert static.get("docker.io") == Credentials("a", "b")
    chained = ChainedCredentials(StaticCredentials({}), static)
    assert chained.get("docker.io") == Credentials("a", "b")
    assert chained.get("ghcr.io") is None
