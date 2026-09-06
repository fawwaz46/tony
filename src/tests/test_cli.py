"""What `tony` itself does when someone types it.

tony does not review anything any more — the reviewing lives in the MCP server
and runs inside the caller's agent. What is left at the command line is
accounts, agent wiring, and the two paths a stranger hits first: typing `tony`
with nothing after it, and typing the range the old tony took directly.

The repository wall (`confine`) is tested here rather than with the diff
helpers because it is a security boundary: the payload builder reads files by
paths that came out of a model.
"""

import json
import subprocess
import time

from tony_cli import agent, hosted, install
from tony_cli.agent import main
from tony_cli.source.local import confine, resolveBase


def makeRepo(path, branch="main"):
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "c1"], check=True)
    return path


# --- the two things a stranger types ----------------------------------------

def test_bare_tony_prints_what_to_do_next(capsys):
    """Nothing after `tony` is not an error state, it is someone who just
    installed it. The answer they need is `tony connect`."""
    assert main([]) == 0
    assert "tony connect" in capsys.readouterr().out


def test_a_range_says_where_the_reviewing_went(capsys):
    """`tony main...HEAD` used to be the whole product. Anyone with that habit
    gets told what replaced it, not an argparse error about an unknown file."""
    assert main(["main...HEAD"]) == 2
    err = capsys.readouterr().err
    assert "no longer reviews on its own" in err
    assert "tony connect" in err


def test_help_is_not_a_failure(capsys):
    assert main(["--help"]) == 0
    assert "tony connect" in capsys.readouterr().out


# --- the base branch must survive a deleted local branch --------------------

def test_resolved_remote_base_keeps_its_remote_spelling(tmp_path):
    repo = makeRepo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(repo)],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref",
                    "refs/remotes/origin/main", "HEAD"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-qD", "main"], check=True)
    assert resolveBase(str(repo)) == "origin/main"


def test_local_base_is_preferred_when_it_exists(tmp_path):
    repo = makeRepo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat"], check=True)
    assert resolveBase(str(repo)) == "main"


# --- reads stay inside the repo under review --------------------------------

def test_confine_accepts_paths_inside(tmp_path):
    (tmp_path / "a.py").write_text("x")
    assert confine(str(tmp_path), str(tmp_path / "a.py")) is not None
    assert confine(str(tmp_path), "a.py") is not None


def test_confine_rejects_escapes(tmp_path):
    assert confine(str(tmp_path), "/etc/passwd") is None
    assert confine(str(tmp_path), str(tmp_path / ".." / "other")) is None
    assert confine(str(tmp_path), "../outside") is None


def test_confine_rejects_symlinks_out(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("s")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "link").symlink_to(outside / "secret")
    assert confine(str(repo), str(repo / "link")) is None


# --- telling someone a release exists ---------------------------------------

def test_no_notice_when_the_index_is_behind_this_machine():
    """A machine that just installed the newest version can be ahead of what
    the index admits exists. That is not an update."""
    assert install.newerVersion("0.4.2", current="0.4.2") is None
    assert install.newerVersion("0.4.1", current="0.4.2") is None
    assert install.newerVersion("0.5.0", current="0.4.2") == "0.5.0"


def test_a_prerelease_is_never_offered():
    """`tony update` will not move anyone onto one, so nothing should announce
    one either."""
    assert install.newerVersion("0.5.0rc1", current="0.4.2") is None


def test_the_notice_falls_back_to_the_last_answer(monkeypatch, tmp_path):
    """The check runs in the background, and plenty of commands finish before
    one HTTP round trip does. The previous run's answer is what makes the
    notice appear at all on a machine like that."""
    cache = tmp_path / "update.json"
    cache.write_text(json.dumps({"latest": "9.9.9", "checkedAt": time.time()}))
    monkeypatch.setattr(install, "CHECK_CACHE", str(cache))
    monkeypatch.setattr(install, "installedVersion", lambda: "0.4.2")

    notice = install.updateNotice(handle=None)
    assert "9.9.9" in notice and "tony update" in notice


def test_a_stale_answer_is_not_repeated_forever(monkeypatch, tmp_path):
    cache = tmp_path / "update.json"
    old = time.time() - install.CACHE_TTL - 1
    cache.write_text(json.dumps({"latest": "9.9.9", "checkedAt": old}))
    monkeypatch.setattr(install, "CHECK_CACHE", str(cache))
    monkeypatch.setattr(install, "installedVersion", lambda: "0.4.2")

    assert install.updateNotice(handle=None) == ""


def test_a_corrupt_cache_is_not_an_error(monkeypatch, tmp_path):
    cache = tmp_path / "update.json"
    cache.write_text("{ not json")
    monkeypatch.setattr(install, "CHECK_CACHE", str(cache))
    assert install.savedCheck() is None


def test_every_command_carries_the_notice(monkeypatch, capsys):
    """The point of the whole thing: someone typing an unrelated command is how
    they find out a release happened."""
    monkeypatch.setattr(install, "startUpdateCheck", lambda: ("handle",))
    monkeypatch.setattr(install, "updateNotice", lambda handle: "tony: 9.9.9 is out")

    assert main([]) == 0
    assert "9.9.9" in capsys.readouterr().err


def test_update_and_mcp_do_not_carry_it():
    """`tony update` would be talking over itself, and `tony mcp` speaks a
    protocol on stdio — it tells the agent instead."""
    for command in ("update", "uninstall", "mcp"):
        assert command in agent.NO_NOTICE


def test_a_source_checkout_is_never_told_to_update(monkeypatch):
    """It updates with `git pull`. Asking PyPI about it would only produce a
    notice nobody can act on."""
    monkeypatch.setattr(install, "isSourceCheckout", lambda: True)
    assert install.startUpdateCheck() is None
