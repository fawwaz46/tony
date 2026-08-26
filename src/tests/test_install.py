"""Reading the install receipt, and `tony --update`.

Both update and uninstall act on the answer to "which tool put this here", and
acting on a wrong answer means running someone else's installer against a
package it does not manage. These pin the detection and the two cases that must
never run an installer at all: a source checkout, and a stray argument.
"""

import subprocess
import sys

import pytest

from tony_cli import install


@pytest.fixture
def notSource(monkeypatch):
    monkeypatch.setattr(install, "isSourceCheckout", lambda: False)
    # No test may reach PyPI. Once tony-cli is published, a test that asked the
    # real index would start taking the "already latest" branch and stop
    # exercising the thing it was written for.
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: None)
    # Default to "something moved", so tests about other things do not trip the
    # guard against reporting a no-op as an upgrade.
    monkeypatch.setattr(install, "installedOnDisk", lambda: "9.9.9")


# --- detection -------------------------------------------------------------

def test_reads_the_receipt_uv_leaves(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    (tmp_path / "uv-receipt.toml").write_text("")
    assert install.installer() == "uv"
    assert install.updateCommand("uv") == ["uv", "tool", "upgrade", "--refresh", "tony-cli"]


def test_reads_the_receipt_pipx_leaves(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    (tmp_path / "pipx_metadata.json").write_text("{}")
    assert install.installer() == "pipx"
    assert install.updateCommand("pipx") == [
        "pipx", "upgrade", "tony-cli", "--pip-args=--no-cache-dir",
    ]


def test_falls_back_to_pip_in_a_plain_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    assert install.installer() == "pip"
    assert install.updateCommand("pip")[:3] == [sys.executable, "-m", "pip"]


def test_update_resolves_from_pypi_not_an_ambient_mirror():
    """A machine pointed at an internal mirror must not decide what tony is."""
    env = install.indexEnv()
    assert env["PIP_INDEX_URL"] == "https://pypi.org/simple"
    assert env["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"


# --- update ----------------------------------------------------------------

def test_update_runs_the_installers_upgrade(notSource, monkeypatch, capsys):
    ran = {}

    def fake(command, env=None):
        ran["command"] = command
        ran["index"] = env["PIP_INDEX_URL"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(subprocess, "run", fake)
    assert install.update() == 0
    assert ran["command"] == ["pipx", "upgrade", "tony-cli", "--pip-args=--no-cache-dir"]
    assert ran["index"] == "https://pypi.org/simple"


def test_update_reports_the_installers_failure(notSource, monkeypatch):
    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(
        subprocess, "run", lambda c, env=None: subprocess.CompletedProcess(c, 3)
    )
    assert install.update() == 3


def test_update_survives_a_missing_installer(notSource, monkeypatch, capsys):
    def missing(command, env=None):
        raise OSError("no pipx")
    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(subprocess, "run", missing)
    assert install.update() == 1
    assert "pipx upgrade tony-cli" in capsys.readouterr().err


def test_update_refuses_on_a_source_checkout(monkeypatch, capsys):
    """Overwriting a working tree from PyPI would destroy uncommitted work."""
    monkeypatch.setattr(install, "isSourceCheckout", lambda: True)
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    assert install.update() == 2
    assert not called
    assert "git pull" in capsys.readouterr().err


def test_update_takes_no_arguments(notSource, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    assert install.update(["0.3.0"]) == 2
    assert not called


# --- dispatch --------------------------------------------------------------

def test_update_is_a_verb_not_a_flag(monkeypatch):
    """`tony update`, alongside login/logout/uninstall.

    It does not modify a review — it cannot run during one — so it is dispatched
    with the other verbs, before the parser reads argv as a repository path.
    """
    from tony_cli import agent

    called = []
    monkeypatch.setattr(install, "update", lambda argv: called.append(argv) or 0)
    assert agent.main(["update"]) == 0
    assert called == [[]]


def test_update_does_not_need_a_repository(tmp_path, monkeypatch):
    """Dispatched before any repo is resolved, so it works from anywhere."""
    from tony_cli import agent

    monkeypatch.chdir(tmp_path)  # not a git repo
    monkeypatch.setattr(install, "update", lambda argv: 0)
    assert agent.main(["update"]) == 0


# --- knowing whether anything actually happened ----------------------------

def test_already_latest_does_not_run_the_installer(notSource, monkeypatch, capsys):
    """Every installer exits 0 for "already at latest".

    Running it anyway prints its output and returns success, which is
    indistinguishable from a real upgrade — tony used to report "updated" to
    someone whose version had not moved.
    """
    monkeypatch.setattr(install, "installedVersion", lambda: "0.3.0")
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: "0.3.0")
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))

    assert install.update() == 0
    assert not called, "installer must not run when there is nothing to do"
    assert "already on the latest version (0.3.0)" in capsys.readouterr().out


def test_a_real_upgrade_reports_both_versions(notSource, monkeypatch, capsys):
    monkeypatch.setattr(install, "installedVersion", lambda: "0.2.0")
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: "0.3.0")
    monkeypatch.setattr(install, "installedOnDisk", lambda: "0.3.0")
    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(
        subprocess, "run", lambda c, env=None: subprocess.CompletedProcess(c, 0)
    )
    assert install.update() == 0
    out = capsys.readouterr().out
    assert "updating to 0.3.0 with pipx" in out
    assert "updated 0.2.0 -> 0.3.0" in out


def test_an_unreachable_index_still_updates(notSource, monkeypatch, capsys):
    """PyPI being unreachable must not block an upgrade, only the reporting."""
    monkeypatch.setattr(install, "installedVersion", lambda: "0.2.0")
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: None)
    monkeypatch.setattr(install, "installedOnDisk", lambda: None)  # no metadata to read
    ran = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda c, env=None: ran.append(c) or subprocess.CompletedProcess(c, 0),
    )
    assert install.update() == 0
    assert ran, "the upgrade still runs"
    assert "Check it with `tony --version`" in capsys.readouterr().out
    assert "updated" not in capsys.readouterr().out


def test_latest_version_survives_a_broken_index(monkeypatch):
    """A 500, an HTML error page, a timeout — none may raise into the CLI."""
    class Boom:
        status_code = 200
        def json(self): raise ValueError("not json")
    monkeypatch.setattr(install.httpx, "get", lambda *a, **k: Boom())
    assert install.latestVersion() is None

    def explode(*a, **k):
        raise install.httpx.ConnectError("no route")
    monkeypatch.setattr(install.httpx, "get", explode)
    assert install.latestVersion() is None


# --- reporting what actually happened, not what was hoped for ---------------

def test_reports_the_version_that_actually_landed(notSource, monkeypatch, capsys):
    """Not the one PyPI called newest.

    An installer resolving against a stale index cache prints "already at latest"
    for a version that is not, and exits 0. Reporting the upgrade from PyPI's
    answer turned that into "updated 0.3.0 -> 0.3.1" on a machine still running
    0.3.0.
    """
    monkeypatch.setattr(install, "installedVersion", lambda: "0.3.0")
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: "0.3.1")
    monkeypatch.setattr(install, "installedOnDisk", lambda: "0.3.0")  # nothing moved
    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(
        subprocess, "run", lambda c, env=None: subprocess.CompletedProcess(c, 0)
    )

    assert install.update() == 1, "a no-op upgrade is not a success"
    err = capsys.readouterr().err
    assert "still 0.3.0" in err
    assert "0.3.1" in err, "says what it should have got"


def test_a_real_upgrade_reads_the_new_version_off_disk(notSource, monkeypatch, capsys):
    monkeypatch.setattr(install, "installedVersion", lambda: "0.3.0")
    monkeypatch.setattr(install, "latestVersion", lambda *a, **k: "0.3.1")
    monkeypatch.setattr(install, "installedOnDisk", lambda: "0.3.1")
    monkeypatch.setattr(install, "installer", lambda: "pipx")
    monkeypatch.setattr(
        subprocess, "run", lambda c, env=None: subprocess.CompletedProcess(c, 0)
    )
    assert install.update() == 0
    assert "updated 0.3.0 -> 0.3.1" in capsys.readouterr().out


def test_on_disk_version_comes_from_the_metadata_directory(tmp_path, monkeypatch):
    """Read from disk, because the imported version is the one being replaced."""
    import sysconfig
    lib = tmp_path / "site-packages"
    lib.mkdir()
    (lib / "tony_cli-0.3.1.dist-info").mkdir()
    monkeypatch.setattr(sysconfig, "get_paths", lambda *a, **k: {"purelib": str(lib)})
    assert install.installedOnDisk() == "0.3.1"


def test_on_disk_version_is_none_when_there_is_no_metadata(tmp_path, monkeypatch):
    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths", lambda *a, **k: {"purelib": str(tmp_path)})
    assert install.installedOnDisk() is None
