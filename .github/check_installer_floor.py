"""Fail if install.sh's minimum version is ahead of the version in pyproject.

release.yml publishes whatever pyproject.toml says, so a floor above that
version asks users for a release that does not exist yet — the install just
fails with "no matching distribution".

Read with a regex rather than tomllib: this runs on the CI matrix, which
includes the 3.10 the project still supports, and tomllib arrived in 3.11.
"""

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent


def find(path, pattern):
    text = (root / path).read_text()
    match = re.search(pattern, text, re.M)
    if not match:
        sys.exit(f"could not find {pattern!r} in {path}")
    return match.group(1)


version = find("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
floor = find("install.sh", r'^MIN="([^"]+)"')


def parts(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


if parts(floor) > parts(version):
    sys.exit(
        f"install.sh asks for tony-cli>={floor}, but pyproject.toml is {version}. "
        f"Bump the version (and tag it) before raising the installer floor."
    )

print(f"installer floor {floor} <= version {version}")
