"""Fail if install.sh's minimum version is ahead of the version in pyproject.

release.yml publishes whatever pyproject.toml says, so a floor above that
version asks users for a release that does not exist yet — the install just
fails with "no matching distribution".
"""

import re
import sys
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parent.parent

version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
floor = re.search(r'^MIN="([^"]+)"', (root / "install.sh").read_text(), re.M).group(1)


def parts(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in v.split("."))


if parts(floor) > parts(version):
    sys.exit(
        f"install.sh asks for tony-cli>={floor}, but pyproject.toml is {version}. "
        f"Bump the version (and tag it) before raising the installer floor."
    )

print(f"installer floor {floor} <= version {version}")
