"""The failure paths a stranger hits first.

A blank page with exit 0 is worse than an error: it looks like tony worked and
found nothing. These pin the loud-failure behaviour, the base-branch spelling
that must survive a deleted local branch, and the wall that keeps the model's
tool calls inside the repo under review.
"""

import subprocess

import pytest

from tony_cli.agent import main, runTool
from tony_cli.source.local import confine, resolveBase


def makeRepo(path, branch="main"):
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "c1"], check=True)
    return path


# --- unparseable review is a loud failure ----------------------------------

def test_unparseable_review_exits_1_and_keeps_raw(tmp_path, monkeypatch, capsys):
    repo = makeRepo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat"], check=True)
    (repo / "f.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "c2"], check=True)

    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "main...HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    truncated = '```json\n{"intent": "cut off mid-'  # no closing fence, no valid JSON

    monkeypatch.setattr(
        "tony_cli.agent.review", lambda *a, **k: (0, truncated, diff)
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    code = main([str(repo), "main...HEAD", "--no-open", "--local"])
    assert code == 1
    err = capsys.readouterr().err
    assert "unparseable" in err
    assert not (repo / ".tony" / "main...HEAD.html").exists()
    raw = repo / ".tony" / "main...HEAD.raw.txt"
    assert raw.exists() and "cut off" in raw.read_text()


def test_parseable_review_writes_a_page(tmp_path, monkeypatch):
    repo = makeRepo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat"], check=True)
    (repo / "f.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "c2"], check=True)
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "main...HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    review = '```json\n{"intent": "adds a line", "annotations": []}\n```'

    monkeypatch.setattr("tony_cli.agent.review", lambda *a, **k: (0, review, diff))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    assert main([str(repo), "main...HEAD", "--no-open", "--local"]) == 0
    page = (repo / ".tony" / "main...HEAD.html").read_text()
    assert "adds a line" in page
    assert 'id="tony-payload"' in page


# --- resolveBase must return something git can diff against ----------------

def test_resolved_remote_base_keeps_its_remote_spelling(tmp_path):
    up = makeRepo(tmp_path / "up")
    dn = tmp_path / "dn"
    subprocess.run(["git", "clone", "-q", str(up), str(dn)], check=True)
    subprocess.run(["git", "-C", str(dn), "checkout", "-qb", "feature"], check=True)
    subprocess.run(["git", "-C", str(dn), "branch", "-qD", "main"], check=True)

    base = resolveBase(str(dn))
    # The local main is gone; a bare "main" would make every diff fail.
    probe = subprocess.run(
        ["git", "-C", str(dn), "rev-parse", "--verify", "--quiet", base],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0, f"resolveBase returned {base!r}, which git cannot resolve"


def test_local_base_is_preferred_when_it_exists(tmp_path):
    repo = makeRepo(tmp_path / "r")
    assert resolveBase(str(repo)) == "main"


# --- tool calls stay inside the repo ----------------------------------------

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


def test_runTool_refuses_reads_outside_the_repo(tmp_path):
    repo = makeRepo(tmp_path / "r")
    out = runTool("readFile", {"path": "/etc/passwd"}, str(repo))
    assert out.startswith("refused:")


def test_runTool_serves_reads_inside_the_repo(tmp_path):
    repo = makeRepo(tmp_path / "r")
    out = runTool("readFile", {"path": str(repo / "f.txt")}, str(repo))
    assert out == "one\n"


# --- flags must fail before the review is paid for --------------------------

def test_json_does_not_demand_an_account(tmp_path, monkeypatch, capsys):
    """--json prints and exits without uploading, so it needs no login.

    It used to share the publish gate, which asked people to sign in to a site
    the run would never contact.
    """
    repo = makeRepo(tmp_path / "r")
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat"], check=True)
    (repo / "f.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "c2"], check=True)

    monkeypatch.setattr("tony_cli.hosted.savedToken", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    code = main([str(repo), "main...HEAD", "--json"])
    err = capsys.readouterr().err
    assert "sign in" not in err          # it got past the publish gate
    assert "ANTHROPIC_API_KEY" in err    # and stopped on the key it does need
    assert code == 2


def test_max_tokens_below_one_is_an_argument_error(tmp_path, capsys):
    """A ceiling no review fits under is a typo, caught before any work."""
    repo = makeRepo(tmp_path / "r")
    assert main([str(repo), "--local", "--max-tokens", "0"]) == 2
    assert "--max-tokens must be at least 1" in capsys.readouterr().err


def test_viewer_without_a_source_install_fails_first(tmp_path, monkeypatch, capsys):
    """Not after a paid-for review — there is nowhere for the payload to go."""
    repo = makeRepo(tmp_path / "r")
    monkeypatch.setattr("tony_cli.agent.viewerFixture", lambda: None)
    assert main([str(repo), "--local", "--viewer"]) == 2
    assert "installed from source" in capsys.readouterr().err
