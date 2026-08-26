"""What `tony uninstall` must never get wrong.

It deletes things, so the tests that matter are the ones about restraint: it
does not delete without a confirmed yes, it does not delete a working tree, and
it does not wander outside the home directory following a symlink. The rest
pins that it actually finds the reviews scattered across repos, which is the
whole reason the command exists — a plain `pipx uninstall` already does the
part everyone remembers.
"""

import os

import pytest

from tony_cli import hosted, uninstall as u
from tony_cli import install


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated home with a config dir and one repo holding reviews."""
    home = tmp_path / "home"
    config = home / ".tony"
    config.mkdir(parents=True)
    (config / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-secret\n")
    (config / "credentials.json").write_text('{"token": "t"}')

    reviews = home / "code" / "repo" / ".tony"
    reviews.mkdir(parents=True)
    (reviews / "main...feat.html").write_text("<html>review</html>")

    monkeypatch.setattr(u, "HOME", str(home))
    monkeypatch.setattr(hosted, "CONFIG_DIR", str(config))
    monkeypatch.setattr(hosted, "CREDENTIALS", str(config / "credentials.json"))
    monkeypatch.setattr(hosted, "savedToken", lambda: None)
    # Not a checkout — that path refuses and is tested on its own. The real
    # uninstaller is blocked one level lower, at the exec that would run it.
    monkeypatch.setattr(u, "isSourceCheckout", lambda: False)
    monkeypatch.setattr(install, "isSourceCheckout", lambda: False)

    def noExec(*a):
        raise SystemExit(0)   # what execvp does to this process, minus the pipx
    monkeypatch.setattr(os, "execvp", noExec)
    monkeypatch.chdir(home)
    return home


# --- finding what to delete ------------------------------------------------

def test_scan_finds_reviews_in_other_repos(home):
    found = u.reportDirs()
    assert str(home / "code" / "repo" / ".tony") in found


def test_scan_never_offers_the_config_dir_as_a_repo(home):
    """~/.tony is deleted deliberately, not as a stray review directory."""
    found = u.reportDirs()
    assert str(home / ".tony") not in found


def test_scan_skips_dependency_trees(home):
    buried = home / "code" / "repo" / "node_modules" / "pkg" / ".tony"
    buried.mkdir(parents=True)
    assert str(buried) not in u.reportDirs()


def test_scan_does_not_follow_symlinks_out_of_home(home, tmp_path):
    outside = tmp_path / "elsewhere" / "other"
    (outside / ".tony").mkdir(parents=True)
    (home / "link").symlink_to(outside)
    assert not any("elsewhere" in p for p in u.reportDirs())


def test_no_scan_still_finds_the_current_repo(home, monkeypatch):
    repo = home / "code" / "repo"
    monkeypatch.chdir(repo)
    assert u.reportDirs(scan=False) == [str(repo / ".tony")]


# --- restraint -------------------------------------------------------------

def test_refuses_without_a_terminal_to_confirm_at(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert u.uninstall([]) == 1
    assert (home / ".tony" / ".env").exists()

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert u.uninstall([]) == 2
    assert (home / ".tony" / ".env").exists()


def test_anything_but_yes_deletes_nothing(home, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert u.uninstall([]) == 1
    assert (home / ".tony" / "credentials.json").exists()
    assert (home / "code" / "repo" / ".tony").exists()


def uninstalled(argv=("--yes",)):
    """Run the uninstall, treating the exec of the package manager as success."""
    try:
        return u.uninstall(list(argv))
    except SystemExit as e:
        return e.code


def test_source_checkout_deletes_nothing_at_all(home, monkeypatch, capsys):
    monkeypatch.setattr(u, "isSourceCheckout", lambda: True)
    """It cannot uninstall a working tree, so it must not do the destructive half.

    Deleting the key and every saved review while leaving the tool installed and
    on PATH is the worst outcome available: `tony --version` reports the same
    number as before, so it reads as a no-op that quietly took the data with it.
    """
    assert u.uninstall(["--yes"]) == 2
    assert (home / ".tony" / ".env").exists()
    assert (home / "code" / "repo" / ".tony").exists()
    err = capsys.readouterr().err
    assert "Nothing was deleted" in err
    assert "pip uninstall tony-cli" in err


# --- deleting --------------------------------------------------------------

def test_yes_removes_the_key_and_every_review(home):
    assert uninstalled() == 0
    assert not (home / ".tony").exists()
    assert not (home / "code" / "repo" / ".tony").exists()
    assert (home / "code" / "repo").exists()  # the repo itself is untouched


def test_revokes_the_site_token_before_deleting_it(home, monkeypatch):
    order = []
    monkeypatch.setattr(hosted, "savedToken", lambda: "tok")
    monkeypatch.setattr(hosted, "logout", lambda: order.append("revoked") or 0)
    real = u.remove
    monkeypatch.setattr(u, "remove", lambda p: order.append(f"rm {p}") or real(p))

    uninstalled()
    assert order[0] == "revoked"


def test_rejects_unknown_flags(home, capsys):
    assert u.uninstall(["--everything"]) == 2
    assert (home / ".tony").exists()

# --- logged out is a normal state, not a broken one ------------------------

def test_uninstall_works_after_logout(home, monkeypatch):
    """`tony logout` then `tony uninstall` must not need a token to finish.

    Logging out deletes credentials.json, so the uninstall that follows finds
    no token to revoke and a config dir with a hole in it. That is the ordinary
    way someone leaves — it cannot be the path that fails.
    """
    monkeypatch.setattr(hosted, "savedToken", lambda: None)
    (home / ".tony" / "credentials.json").unlink()  # what logout leaves behind

    def refuse():
        raise AssertionError("uninstall tried to log out with no token")
    monkeypatch.setattr(hosted, "logout", refuse)

    assert uninstalled() == 0
    assert not (home / ".tony").exists()          # the API key still goes
    assert not (home / "code" / "repo" / ".tony").exists()


def test_uninstall_with_no_config_dir_at_all(home, monkeypatch):
    """Nothing to delete is a success, not an error — someone may run this twice."""
    import shutil
    shutil.rmtree(home / ".tony")
    monkeypatch.setattr(hosted, "savedToken", lambda: None)
    assert uninstalled() == 0


def test_failed_deletion_leaves_tony_installed(home, monkeypatch, capsys):
    """Removing the package would strip the only thing that knows what is left.

    A permission error on one review directory must leave tony in place so the
    command can be retried, not remove the tool and orphan the files.
    """
    monkeypatch.setattr(u, "isSourceCheckout", lambda: False)
    monkeypatch.setattr(u, "remove", lambda path: False)
    monkeypatch.setattr(hosted, "savedToken", lambda: None)

    def refuse(*a):
        raise AssertionError("uninstalled the package after a failed deletion")
    monkeypatch.setattr(os, "execvp", refuse)

    assert u.uninstall(["--yes"]) == 1
    assert "left" in capsys.readouterr().err
