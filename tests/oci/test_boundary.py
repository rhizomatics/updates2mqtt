"""The OCI client must stay separable: no imports from the rest of updates2mqtt, and only the
standard library in the core, with each HTTP library confined to its own transport"""

import ast
import sys
from pathlib import Path

import pytest

OCI_ROOT = Path(__file__).parents[2] / "src" / "updates2mqtt" / "oci"
# third party imports allowed per module, relative to the oci package
ALLOWED_THIRD_PARTY: dict[str, set[str]] = {
    "transports/httpx_transport.py": {"httpx"},
    "transports/niquests_transport.py": {"niquests"},
}
MODULES: list[Path] = sorted(OCI_ROOT.rglob("*.py"))


def imported(path: Path) -> list[tuple[str, int]]:
    """Top level module of each absolute import, and depth of each relative one, as (name, level)"""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_modules_found() -> None:
    assert len(MODULES) >= 8


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(OCI_ROOT)))
def test_imports_stay_inside(path: Path) -> None:
    relative: str = path.relative_to(OCI_ROOT).as_posix()
    # how many levels up a relative import can go and still be within oci
    depth: int = len(path.relative_to(OCI_ROOT).parts)
    allowed: set[str] = ALLOWED_THIRD_PARTY.get(relative, set())
    for name, level in imported(path):
        if level:
            assert level <= depth, f"{relative} imports outside the oci package: {'.' * level}{name}"
            continue
        top: str = name.split(".")[0]
        if top == "updates2mqtt":
            assert name == "updates2mqtt.oci" or name.startswith("updates2mqtt.oci."), f"{relative} imports {name}"
            continue
        assert top in sys.stdlib_module_names or top == "__future__" or top in allowed, f"{relative} imports third party {name}"
