"""Approving a sandboxed agent: the CLI half.

A sandbox has no browser for `tony login`, so tony_start asks the site for an
approval link, the agent shows it, and the next tony_start collects a token
with a poll key that never leaves the machine. These pin that a machine with
no token never starts a review, that the link and code reach the agent
exactly, that the token is collected once and saved privately, and that the
agent is told which account it will publish to.
"""

import json
import os
import stat
import subprocess

import pytest

from tony_cli import hosted, mcp_server
from tony_cli.mcp_server import startReview


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A fresh ~/.tony and a fake site for every test; nothing touches the network."""
    monkeypatch.setattr(hosted, "CONFIG_DIR", str(tmp_path / ".tony"))
    monkeypatch.setattr(hosted, "CREDENTIALS", str(tmp_path / ".tony" / "credentials.json"))
    monkeypatch.setattr(hosted, "LINK", str(tmp_path / ".tony" / "link.json"))
    monkeypatch.setenv("TONY_API_URL", "https://site.test")
    monkeypatch.setattr(hosted.time, "sleep", lambda *_: None)
    mcp_server.SESSIONS.clear()
    yield
    mcp_server.SESSIONS.clear()


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


LINK = {"url": "https://site.test/link/" + "a" * 64, "code": "K7F2QX",
        "pollKey": "b" * 64, "expiresIn": 600}


def site(monkeypatch, polls=()):
    """Answer /api/link with LINK and /api/link/poll from `polls`, in order."""
    calls = {"link": [], "poll": []}
    queue = list(polls)

    def post(url, **kwargs):
        if url.endswith("/api/link"):
            calls["link"].append(kwargs.get("json"))
            return FakeResponse(LINK)
        if url.endswith("/api/link/poll"):
            calls["poll"].append(kwargs.get("json"))
            return queue.pop(0)
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(hosted.httpx, "post", post)
    return calls


def makeRepo(path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "c1"], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-qb", "feature"], check=True)
    (path / "f.txt").write_text("two\n")
    subprocess.run(["git", "-C", str(path), "commit", "-qam", "c2"], check=True)
    return path


def ready(monkeypatch):
    """Everything tony_start needs past sign-in, without the network."""
    monkeypatch.setattr(hosted, "fetchInstructions",
                        lambda: ({"version": "v", "document": "DOC"}, None))
    monkeypatch.setattr(mcp_server.install, "startUpdateCheck", lambda: None)
    monkeypatch.setattr(mcp_server.install, "pendingUpdate", lambda check: None)


# --- hosted ----------------------------------------------------------------

def test_starting_a_link_keeps_the_poll_key_private(monkeypatch):
    calls = site(monkeypatch)
    link, problem = hosted.startLink(agent="amp")
    assert problem is None and link["code"] == "K7F2QX"
    assert calls["link"] == [{"agent": "amp"}]
    mode = stat.S_IMODE(os.stat(hosted.LINK).st_mode)
    assert mode == 0o600, "the poll key is a credential until spent"
    assert json.load(open(hosted.LINK))["pollKey"] == "b" * 64


def test_collecting_saves_the_token_once_approved(monkeypatch):
    site(monkeypatch, polls=[FakeResponse({"status": "pending"}, 202),
                             FakeResponse({"status": "approved", "token": "tok", "login": "fawwaz"})])
    hosted.startLink()
    assert hosted.collectLink() == ("approved", "fawwaz")
    assert hosted.savedToken() == "tok" and hosted.savedLogin() == "fawwaz"
    assert not os.path.exists(hosted.LINK), "a spent link is forgotten"
    assert stat.S_IMODE(os.stat(hosted.CREDENTIALS).st_mode) == 0o600


def test_collecting_gives_up_waiting_without_hanging(monkeypatch):
    """One tool call waits a bounded time, then says 'still pending'."""
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(hosted.time, "monotonic", lambda: next(clock))
    site(monkeypatch, polls=[FakeResponse({"status": "pending"}, 202)] * 50)
    hosted.startLink()
    assert hosted.collectLink(wait=20) == ("pending", None)
    assert hosted.pendingLink(), "a pending link is kept for the next call"


def test_an_expired_link_is_forgotten(monkeypatch):
    site(monkeypatch, polls=[FakeResponse({"status": "expired"}, 404)])
    hosted.startLink()
    assert hosted.collectLink() == ("expired", None)
    assert hosted.pendingLink() is None and hosted.savedToken() is None


def test_a_link_past_its_time_is_not_used(monkeypatch):
    site(monkeypatch)
    hosted.startLink()
    data = json.load(open(hosted.LINK))
    data["expiresAt"] = 0
    json.dump(data, open(hosted.LINK, "w"))
    assert hosted.pendingLink() is None


def test_logout_forgets_a_pending_link(monkeypatch, capsys):
    site(monkeypatch)
    hosted.startLink()
    hosted.logout()
    assert hosted.pendingLink() is None


# --- tony_start --------------------------------------------------------------

def test_no_token_starts_a_link_and_never_the_review(tmp_path, monkeypatch):
    calls = site(monkeypatch)
    ready(monkeypatch)
    out = startReview(str(makeRepo(tmp_path)), range="main...feature", harness=("amp", "1"))
    assert LINK["url"] in out and "K7F2QX" in out
    assert "Do not write the review" in out and "--- THE DIFF ---" not in out
    assert calls["link"] == [{"agent": "amp"}], "the page can say which agent asked"
    assert not mcp_server.SESSIONS, "no review session before there is a token"


def test_still_waiting_shows_the_same_link_again(tmp_path, monkeypatch):
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(hosted.time, "monotonic", lambda: next(clock))
    calls = site(monkeypatch, polls=[FakeResponse({"status": "pending"}, 202)] * 50)
    ready(monkeypatch)
    repo = str(makeRepo(tmp_path))
    startReview(repo, range="main...feature")
    out = startReview(repo, range="main...feature")
    assert "still waiting" in out and LINK["url"] in out
    assert len(calls["link"]) == 1, "a pending link is reused, not replaced"


def test_once_approved_the_review_starts_and_names_the_account(tmp_path, monkeypatch):
    site(monkeypatch, polls=[FakeResponse({"status": "approved", "token": "tok", "login": "fawwaz"})])
    ready(monkeypatch)
    repo = str(makeRepo(tmp_path))
    startReview(repo, range="main...feature")
    out = startReview(repo, range="main...feature")
    assert "--- THE DIFF ---" in out
    assert "account: fawwaz (just approved)" in out, "a wrong account is caught before upload"


def test_an_expired_link_is_replaced_by_a_fresh_one(tmp_path, monkeypatch):
    calls = site(monkeypatch, polls=[FakeResponse({"status": "expired"}, 404)])
    ready(monkeypatch)
    repo = str(makeRepo(tmp_path))
    startReview(repo, range="main...feature")
    out = startReview(repo, range="main...feature")
    assert LINK["url"] in out and len(calls["link"]) == 2


def test_a_site_that_cannot_be_reached_points_at_tony_login(tmp_path, monkeypatch):
    def down(*a, **k):
        raise hosted.httpx.ConnectError("down")
    monkeypatch.setattr(hosted.httpx, "post", down)
    ready(monkeypatch)
    out = startReview(str(makeRepo(tmp_path)), range="main...feature")
    assert "tony login" in out and "--- THE DIFF ---" not in out


def test_a_signed_in_machine_names_its_account(tmp_path, monkeypatch):
    hosted.saveToken("tok", "fawwaz")
    ready(monkeypatch)
    out = startReview(str(makeRepo(tmp_path)), range="main...feature")
    assert "account: fawwaz\n" in out and "just approved" not in out
