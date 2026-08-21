"""Publishing to the tony site.

The payload is uploaded as JSON over TLS and sealed by the server before it
reaches storage. An earlier design encrypted here and put the key in the URL
fragment so the site could never read a review; that was dropped deliberately
when reading was gated behind an account and a history of past reviews became
part of the product — both require the server to be able to open a review.
So: reviews are confidential against a leak of the stored blobs, not against
the site itself. `tony --publish` says as much the first time you use it.

Login is GitHub's device flow, the same shape as `gh auth login`: tony prints a
code, you approve it in a browser, tony polls. The GitHub token is traded to the
tony API for tony's own token, which is what gets cached — the GitHub token is
never stored.
"""

import json
import os
import stat
import sys
import time

import httpx

GITHUB_DEVICE_CODE = "https://github.com/login/device/code"
GITHUB_DEVICE_TOKEN = "https://github.com/login/oauth/access_token"

# The site tony publishes to. Overridable for local development, but it has a
# real default because publishing is the default path — a fresh install should
# work without anyone setting an environment variable.
DEFAULT_API_URL = "https://tony-cli.com"

CONFIG_DIR = os.path.expanduser(os.path.join("~", ".tony"))
CREDENTIALS = os.path.join(CONFIG_DIR, "credentials.json")


def apiBase():
    """Where the tony site lives."""
    return (os.environ.get("TONY_API_URL") or DEFAULT_API_URL).rstrip("/")


# --- credentials -----------------------------------------------------------

def savedToken():
    try:
        with open(CREDENTIALS, encoding="utf-8") as fh:
            return json.load(fh).get("token")
    except (OSError, json.JSONDecodeError):
        return None


def saveToken(token, login):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CREDENTIALS, "w", encoding="utf-8") as fh:
        json.dump({"token": token, "githubLogin": login}, fh)
    os.chmod(CREDENTIALS, stat.S_IRUSR | stat.S_IWUSR)


def clearToken():
    try:
        os.remove(CREDENTIALS)
        return True
    except OSError:
        return False


# --- login -----------------------------------------------------------------

def login():
    """GitHub device flow, then trade the GitHub token for a tony API token.

    Returns 0 on success, non-zero on failure, and prints its own messages —
    this is a user-facing command, not a library call.
    """
    base = apiBase()
    if not base:
        print("tony: TONY_API_URL is not set — there is no site to log in to yet.",
              file=sys.stderr)
        return 2

    # The GitHub OAuth client id is public by design; the server owns it so the
    # CLI never has to ship one.
    try:
        config = httpx.get(f"{base}/api/config", timeout=10).json()
        clientId = config.get("githubClientId") or ""
    except Exception as e:
        print(f"tony: could not reach {base}: {e}", file=sys.stderr)
        return 1
    if not clientId:
        print("tony: the site has no GitHub app configured, so login cannot start.",
              file=sys.stderr)
        return 1

    try:
        device = httpx.post(
            GITHUB_DEVICE_CODE,
            data={"client_id": clientId, "scope": "read:user"},
            headers={"Accept": "application/json"},
            timeout=10,
        ).json()
    except httpx.HTTPError as e:
        print(f"tony: could not reach GitHub: {e}", file=sys.stderr)
        return 1

    # A GitHub OAuth app has device flow OFF by default, and that shows up
    # here rather than at approval time. Say which switch is missing instead
    # of dying on a missing key.
    if "user_code" not in device:
        detail = device.get("error_description") or device.get("error") or "unknown error"
        print(f"tony: GitHub would not start a device login — {detail}.", file=sys.stderr)
        if device.get("error") == "device_flow_disabled":
            print("      Enable 'Device flow' in the GitHub OAuth app's settings.",
                  file=sys.stderr)
        return 1

    print(f"\n  First, copy this code: {device['user_code']}")
    print(f"  Then approve it at:    {device['verification_uri']}\n")
    print("  Waiting for approval — press Ctrl-C to give up.", file=sys.stderr)

    interval = int(device.get("interval", 5))
    deadline = time.time() + int(device.get("expires_in", 900))
    githubToken = None
    try:
        while time.time() < deadline:
            time.sleep(interval)
            try:
                poll = httpx.post(
                    GITHUB_DEVICE_TOKEN,
                    data={
                        "client_id": clientId,
                        "device_code": device["device_code"],
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers={"Accept": "application/json"},
                    timeout=10,
                ).json()
            except httpx.HTTPError:
                # A blip mid-approval should not lose a code the user already
                # typed in; the deadline still bounds this.
                continue

            error = poll.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "expired_token":
                break
            if error:
                detail = poll.get("error_description") or error
                print(f"tony: GitHub declined the login — {detail}.", file=sys.stderr)
                return 1
            githubToken = poll.get("access_token")
            break
    except KeyboardInterrupt:
        print("\ntony: login cancelled.", file=sys.stderr)
        return 1

    if not githubToken:
        print("tony: the code expired before it was approved. Run tony login again.",
              file=sys.stderr)
        return 1

    try:
        exchanged = httpx.post(
            f"{base}/api/auth/github",
            json={"accessToken": githubToken},
            timeout=15,
        )
    except httpx.HTTPError as e:
        print(f"tony: approved, but could not reach {base}: {e}", file=sys.stderr)
        return 1
    if exchanged.status_code != 200:
        print(f"tony: the tony API rejected the login ({exchanged.status_code}).",
              file=sys.stderr)
        return 1

    body = exchanged.json()
    saveToken(body["token"], body.get("githubLogin", ""))
    print(f"tony: logged in as {body.get('githubLogin', 'you')}.")
    return 0


def whoami():
    """Who this machine is logged in as, if anyone."""
    try:
        with open(CREDENTIALS, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, json.JSONDecodeError):
        print("tony: not logged in. Run `tony login` to publish reviews.")
        return 1
    print(f"tony: logged in as {saved.get('githubLogin') or 'unknown'}.")
    return 0


def logout():
    """Revoke this machine's token server-side, then forget it locally.

    Deleting the local file alone would leave a working token in anyone's hands
    who had already copied it, so the revoke comes first — but a site that is
    unreachable must not strand someone logged in on a laptop they are trying
    to wipe, so local removal happens either way.
    """
    token = savedToken()
    if token and apiBase():
        try:
            httpx.post(
                f"{apiBase()}/api/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except httpx.HTTPError:
            print("tony: could not reach the site to revoke this token; "
                  "removing it locally anyway.", file=sys.stderr)

    if clearToken():
        print("tony: logged out.")
    else:
        print("tony: you were not logged in.")
    return 0


# --- encrypt and upload ----------------------------------------------------

def publish(payloadJson, repo="", rangeLabel=""):
    """Upload one payload. Returns (url, problem)."""
    base = apiBase()
    if not base:
        return None, (
            "TONY_API_URL is not set. Publishing needs a deployed tony site — "
            "the local page in .tony/ works without one."
        )
    token = savedToken()
    if not token:
        return None, "not logged in — run `tony login` first."

    try:
        resp = httpx.post(
            f"{base}/api/reviews",
            content=payloadJson.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
    except httpx.HTTPError as e:
        return None, f"could not reach {base}: {e}"

    if resp.status_code == 401:
        return None, "your login expired — run `tony login` again."
    if resp.status_code == 413:
        return None, "this review is over the upload size limit."
    if resp.status_code != 200:
        return None, f"upload failed ({resp.status_code})."

    body = resp.json()
    print(f"tony: to remove it later: tony unpublish {body['id']}", file=sys.stderr)
    return f"{base}/r/{body['id']}", None


def unpublish(reviewId):
    """Delete one of your own published reviews."""
    base = apiBase()
    if not base:
        print("tony: TONY_API_URL is not set.", file=sys.stderr)
        return 2
    token = savedToken()
    if not token:
        print("tony: not logged in — run `tony login` first.", file=sys.stderr)
        return 2
    try:
        resp = httpx.request(
            "DELETE",
            f"{base}/api/reviews/{reviewId}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except httpx.HTTPError as e:
        print(f"tony: could not reach {base}: {e}", file=sys.stderr)
        return 1

    if resp.status_code == 200:
        print("tony: removed.")
        return 0
    if resp.status_code == 403:
        print("tony: that review belongs to someone else.", file=sys.stderr)
    elif resp.status_code == 404:
        print("tony: no such review.", file=sys.stderr)
    else:
        print(f"tony: could not remove it ({resp.status_code}).", file=sys.stderr)
    return 1
