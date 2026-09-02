"""The device-flow state machine, exercised without a network.

Login is the one flow a user cannot retry their way out of if it dies badly:
they have already typed a code into GitHub by the time most of it runs. These
drive the whole state machine against a fake GitHub and a fake site, including
the paths that used to raise instead of explaining — a GitHub app with device
flow switched off, a slow_down, an expired code, a dropped connection.

`deviceLogin` rather than `login`, deliberately: `login` opens a browser first
and only falls back to this, so calling it here would be a test that waits five
minutes for a browser nobody is looking at.
"""

import gzip
import json
import threading
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from tony_cli import hosted


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Credentials land in a scratch home, never the real ~/.tony."""
    monkeypatch.setattr(hosted, "CONFIG_DIR", str(tmp_path / ".tony"))
    monkeypatch.setattr(hosted, "CREDENTIALS", str(tmp_path / ".tony" / "credentials.json"))
    monkeypatch.setenv("TONY_API_URL", "https://site.test")
    monkeypatch.setattr(hosted.time, "sleep", lambda *_: None)
    return tmp_path


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def wire(monkeypatch, *, config=None, device=None, polls=None, exchange=None):
    """Point hosted.py's httpx calls at canned answers."""
    config = {"githubClientId": "cid"} if config is None else config
    device = device if device is not None else {
        "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "device_code": "dev123",
        "interval": 1,
        "expires_in": 900,
    }
    polls = list(polls or [{"access_token": "gho_test"}])
    exchange = exchange or FakeResponse({"token": "tony_tok", "githubLogin": "octocat"})

    monkeypatch.setattr(hosted.httpx, "get", lambda *a, **k: FakeResponse(config))

    def post(url, **kwargs):
        if url == hosted.GITHUB_DEVICE_CODE:
            return FakeResponse(device)
        if url == hosted.GITHUB_DEVICE_TOKEN:
            step = polls.pop(0)
            if isinstance(step, Exception):
                raise step
            return FakeResponse(step)
        return exchange

    monkeypatch.setattr(hosted.httpx, "post", post)


# --- the happy path --------------------------------------------------------

def test_login_saves_a_token_and_reports_the_account(monkeypatch, capsys):
    wire(monkeypatch)
    assert hosted.deviceLogin() == 0

    out = capsys.readouterr().out
    assert "ABCD-1234" in out            # the code the user must type
    assert "github.com/login/device" in out
    assert "octocat" in out

    assert hosted.savedToken() == "tony_tok"


def test_saved_credentials_are_owner_only(monkeypatch):
    import os
    import stat

    wire(monkeypatch)
    hosted.deviceLogin()
    mode = stat.S_IMODE(os.stat(hosted.CREDENTIALS).st_mode)
    assert mode == 0o600, f"credentials are {oct(mode)}, should be 0600"


def test_pending_then_approved(monkeypatch):
    wire(monkeypatch, polls=[
        {"error": "authorization_pending"},
        {"error": "authorization_pending"},
        {"access_token": "gho_test"},
    ])
    assert hosted.deviceLogin() == 0
    assert hosted.savedToken() == "tony_tok"


def test_slow_down_backs_off_and_still_completes(monkeypatch):
    wire(monkeypatch, polls=[{"error": "slow_down"}, {"access_token": "gho_test"}])
    assert hosted.deviceLogin() == 0


def test_a_dropped_poll_does_not_lose_the_login(monkeypatch):
    wire(monkeypatch, polls=[
        httpx.ConnectError("network blip"),
        {"access_token": "gho_test"},
    ])
    assert hosted.deviceLogin() == 0
    assert hosted.savedToken() == "tony_tok"


# --- the ways it can fail --------------------------------------------------

def test_device_flow_disabled_explains_the_switch(monkeypatch, capsys):
    # GitHub OAuth apps ship with device flow OFF; this is the likely first failure.
    wire(monkeypatch, device={
        "error": "device_flow_disabled",
        "error_description": "Device Flow has not been enabled",
    })
    assert hosted.deviceLogin() == 1
    err = capsys.readouterr().err
    assert "Device flow" in err
    assert hosted.savedToken() is None


def test_site_without_a_github_app_says_so(monkeypatch, capsys):
    wire(monkeypatch, config={"githubClientId": ""})
    assert hosted.deviceLogin() == 1
    assert "no GitHub app configured" in capsys.readouterr().err


def test_expired_code_tells_you_to_retry(monkeypatch, capsys):
    wire(monkeypatch, polls=[{"error": "expired_token"}])
    assert hosted.deviceLogin() == 1
    assert "expired" in capsys.readouterr().err
    assert hosted.savedToken() is None


def test_access_denied_is_reported_not_retried(monkeypatch, capsys):
    wire(monkeypatch, polls=[
        {"error": "access_denied", "error_description": "The user cancelled"},
    ])
    assert hosted.deviceLogin() == 1
    assert "cancelled" in capsys.readouterr().err


def test_unreachable_site_fails_before_asking_for_a_code(monkeypatch, capsys):
    monkeypatch.setattr(
        hosted.httpx, "get",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    )
    assert hosted.deviceLogin() == 1
    assert "could not reach" in capsys.readouterr().err


def test_site_rejecting_the_exchange_saves_nothing(monkeypatch, capsys):
    wire(monkeypatch, exchange=FakeResponse({}, status=401))
    assert hosted.deviceLogin() == 1
    assert "rejected" in capsys.readouterr().err
    assert hosted.savedToken() is None


def test_the_site_has_a_default_so_a_fresh_install_just_works(monkeypatch):
    # Publishing is the default path, so a new user must not have to set an
    # environment variable before `tony login` does anything.
    monkeypatch.delenv("TONY_API_URL", raising=False)
    assert hosted.apiBase() == hosted.DEFAULT_API_URL
    assert hosted.apiBase().startswith("https://")


def test_tony_api_url_overrides_the_default(monkeypatch):
    monkeypatch.setenv("TONY_API_URL", "http://localhost:4343/")
    assert hosted.apiBase() == "http://localhost:4343"


# --- what the account commands report --------------------------------------

def test_whoami_before_and_after(monkeypatch, capsys):
    assert hosted.whoami() == 1
    assert "not signed in" in capsys.readouterr().out

    wire(monkeypatch)
    hosted.deviceLogin()
    capsys.readouterr()

    assert hosted.whoami() == 0
    assert "octocat" in capsys.readouterr().out


def test_logout_revokes_server_side_then_forgets_locally(monkeypatch, capsys):
    wire(monkeypatch)
    hosted.deviceLogin()

    revoked = {}

    def post(url, **kwargs):
        revoked["url"] = url
        revoked["auth"] = kwargs.get("headers", {}).get("Authorization")
        return FakeResponse({"ok": True})

    monkeypatch.setattr(hosted.httpx, "post", post)
    assert hosted.logout() == 0

    assert revoked["url"].endswith("/api/auth/logout")
    assert revoked["auth"] == "Bearer tony_tok"
    assert hosted.savedToken() is None


def test_logout_still_clears_locally_when_the_site_is_down(monkeypatch, capsys):
    wire(monkeypatch)
    hosted.deviceLogin()
    monkeypatch.setattr(
        hosted.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    assert hosted.logout() == 0
    assert hosted.savedToken() is None


# --- publish refuses to spend anything without a login ---------------------

def test_publish_without_login_is_refused(monkeypatch):
    url, problem = hosted.publish('{"v":1}')
    assert url is None
    assert "not logged in" in problem


def test_publish_without_login_is_refused_even_with_the_default_site(monkeypatch):
    monkeypatch.delenv("TONY_API_URL", raising=False)
    url, problem = hosted.publish('{"v":1}')
    assert url is None
    assert "not logged in" in problem


def test_publish_uploads_and_returns_a_clean_link(monkeypatch, capsys):
    wire(monkeypatch)
    hosted.deviceLogin()
    sent = {}

    def post(url, **kwargs):
        sent["url"] = url
        sent["body"] = kwargs.get("content")
        sent["auth"] = kwargs["headers"]["Authorization"]
        sent["type"] = kwargs["headers"]["Content-Type"]
        return FakeResponse({"id": "abc123"})

    monkeypatch.setattr(hosted.httpx, "post", post)
    url, problem = hosted.publish('{"v":1,"secret":"source code"}', repo="r", rangeLabel="a...b")

    assert problem is None
    assert url == "https://site.test/r/abc123"
    assert sent["auth"] == "Bearer tony_tok"
    # Gzipped on the wire — the site's size limit is measured on what arrives,
    # so this is what lets a large review publish at all.
    assert sent["body"][:2] == b"\x1f\x8b"
    assert sent["type"] == "application/gzip"
    assert json.loads(gzip.decompress(sent["body"])) == {"v": 1, "secret": "source code"}
    assert "abc123" in capsys.readouterr().err


# --- the browser flow ------------------------------------------------------
#
# The loopback listener is reachable by any page the user's browser happens to
# be on, so what it refuses matters as much as what it accepts.

class Listener:
    """A real `browserLogin` server, driven by real requests on a real port.

    The fake browser is also the signal that the port is up: `browserLogin`
    only opens one once it is listening, so the event it sets is exactly the
    moment a request can be sent. Polling with `time.sleep` would not work here
    — the fixture above no-ops it for the whole process.
    """

    def __init__(self, monkeypatch, exchange):
        self.opened = []
        self.listening = threading.Event()

        def open(url):
            self.opened.append(url)
            self.listening.set()
            return True

        monkeypatch.setattr(hosted.webbrowser, "open", open)
        monkeypatch.setattr(hosted, "exchangeCliCode", exchange)

    def run(self):
        """Start the login and wait until it is listening."""
        self.result = {}

        def login():
            self.result["code"] = hosted.browserLogin()

        # A daemon thread so a login left waiting can never hold the suite open
        # for the full five-minute timeout.
        self.thread = threading.Thread(target=login, daemon=True)
        self.thread.start()
        assert self.listening.wait(10), "browserLogin never opened a browser"

        params = parse_qs(urlparse(self.opened[0]).query)
        self.port = params["cli"][0]
        self.state = params["state"][0]
        return self

    def visit(self, **params):
        url = f"http://127.0.0.1:{self.port}/?" + urlencode(params)
        try:
            self.response = httpx.get(url, follow_redirects=False, timeout=5)
        except httpx.HTTPError:
            self.response = None
        self.thread.join(timeout=10)
        return self.result.get("code")


def test_the_browser_flow_saves_the_token_it_is_handed(monkeypatch, capsys):
    listener = Listener(monkeypatch, lambda code: {"token": "tok", "login": "octocat"}).run()
    assert listener.visit(code="c0de", state=listener.state) == 0
    assert hosted.savedToken() == "tok"
    # The browser is sent back to the site to be told it worked, named.
    assert listener.response.status_code == 302
    assert listener.response.headers["Location"].endswith("/cli/done?as=octocat")


def test_a_request_without_the_nonce_is_refused(monkeypatch):
    """Any page the user is browsing can hit this port. The nonce is the wall."""
    called = []
    listener = Listener(monkeypatch, lambda code: called.append(code) or {"token": "t"}).run()
    listener.visit(code="c0de", state="not-the-state")
    assert called == [], "a code arrived with the wrong nonce and was still spent"
    assert hosted.savedToken() is None
    # The real browser never came, so the login is still waiting — end it.
    listener.visit(code="c0de", state=listener.state)


def test_a_failed_exchange_is_reported_not_saved(monkeypatch, capsys):
    listener = Listener(monkeypatch, lambda code: {"error": "the site rejected it."}).run()
    assert listener.visit(code="c0de", state=listener.state) == 1
    assert hosted.savedToken() is None
    assert "the site rejected it." in capsys.readouterr().err


def test_no_browser_asks_the_caller_to_fall_back(monkeypatch):
    """A headless box must land on the device flow, not on a five-minute wait."""
    monkeypatch.setattr(hosted.webbrowser, "open", lambda url: False)
    assert hosted.browserLogin() == hosted.NO_BROWSER
