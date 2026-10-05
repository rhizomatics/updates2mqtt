import uuid
from unittest.mock import Mock

from docker.models.containers import Container
from docker.models.images import Image

DIGESTS: dict[str, tuple[str, str]] = {}


def digest_for_ref(v: str, short: bool = True) -> str:
    v = v.replace("library/", "")
    d: str = DIGESTS.get(v, ["!!", "!!!"])[0]
    # match v:
    #     case "testy/mctest:latest":
    #         d = "sha256:c53853875750"
    #     case "testy/mctest":
    #         d = "sha256:9e2bbca079382"
    #     case "ubuntu":
    #         d = "sha256:85a5385853bd3"
    #     case _:
    #         d = "sha256:9999999999999"
    return d[:19] if short else f"{d}{'0' * 52}"[:64]


def repo_digest_for_ref(v: str, short: bool = True) -> str:
    v = v.replace("library/", "")
    d: str = DIGESTS.get(v, ["??", "???"])[1]
    # match v:
    #     case "testy/mctest:latest":
    #         d = "sha256:d019382983f2"
    #     case "testy/mctest":
    #         d = "sha256:c6c6c6c6c6c6"
    #     case "ubuntu":
    #         d = "sha256:babababababa"
    #     case _:
    #         d = "sha256:33333333333"
    return d[:19] if short else f"{d}{'0' * 52}"[:64]


def build_mock_container(
    tag: str,
    name: str | None = None,
    picture: str | None = None,
    relnotes: str | None = None,
    opsys: str = "linux",
    arch: str = "arm64",
    update_available: bool = True,
) -> Container:
    c = Mock(spec=Container)
    c.image = Mock(spec=Image)
    c.name = name or uuid.uuid4().hex
    c.image.tags = [tag]
    c.image.labels = {}
    c.image.attrs = {}
    c.image.attrs["Os"] = opsys
    c.image.attrs["Architecture"] = arch
    bare_tag = tag.split(":", maxsplit=1)[0]

    if update_available:
        repo_digest = f"sha256:{uuid.uuid4().hex}"
        image_digest = f"sha256:{uuid.uuid4().hex}"
        DIGESTS[tag] = (f"sha256:{uuid.uuid4().hex}", f"sha256:{uuid.uuid4().hex}")
    else:
        repo_digest = "sha256:1111bca079387d7965c3a9cee6d0c53f4f4e63ff7637877a83c4c05f2a666112"
        image_digest = "sha256:9999bca079387d7965c3a9cee6d0c53f4f4e63ff7637877a83c4c05f2a666112"
        DIGESTS[tag] = (image_digest, repo_digest)

    # "9e2bbca079387d7965c3a9cee6d0c53f4f4e63ff7637877a83c4c05f2a666112"
    c.image.attrs["RepoDigests"] = [f"{bare_tag}@{repo_digest}"]
    c.labels = {}
    c.attrs = {}
    c.attrs["Config"] = {}
    c.attrs["Image"] = f"{bare_tag}@{image_digest}"
    c.attrs["Config"]["Env"] = []
    c.attrs["Config"]["Labels"] = c.labels
    c.attrs["Config"]["Image"] = tag
    if picture:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_PICTURE={picture}")
    if relnotes:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_RELNOTES={relnotes}")
    return c
