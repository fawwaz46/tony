"""The gate that replaces owning the loop.

Under agent-native tony controls no model, no harness, and no context window,
so the only two places it can still enforce anything are what `tony_start`
refuses to begin and what `tony_publish` refuses to render. These pin both —
including that a rejection names the specific thing to fix, because what reads
it is a model deciding what to change rather than a person reading a traceback.
"""

import json
import subprocess

import pytest

from tony_cli import mcp_server
from tony_cli.mcp_server import annotationProblems, rejection, startReview, validate


@pytest.fixture(autouse=True)
def freshSessions():
    """Sessions outlive a review on purpose, so a test must not inherit one."""
    mcp_server.SESSIONS.clear()
    yield
    mcp_server.SESSIONS.clear()


def makeRepo(path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "f.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "c1"], check=True)
    return path


def note(**over):
    base = {"path": "a.py", "line": 3, "title": "T", "kind": "added", "now": "It runs."}
    return {**base, **over}


def review(**over):
    return {"intent": "Does a thing.", "annotations": [note()], **over}


# --- validation ------------------------------------------------------------

def test_a_complete_review_passes():
    assert validate(review()) == []


def test_missing_intent_is_named():
    assert any("`intent`" in p for p in validate(review(intent="")))


def test_a_changed_annotation_needs_all_three_panes():
    """`prev`, `now`, and `impact` are read as separate panes; two of three is a hole."""
    problems = annotationProblems(0, note(kind="changed", prev="", impact=""))
    assert any("`prev`" in p for p in problems)
    assert any("`impact`" in p for p in problems)


def test_an_added_annotation_may_not_carry_a_prev():
    """A `prev` on new code means a previous version was invented, not observed."""
    problems = annotationProblems(0, note(kind="added", prev="It used to do X."))
    assert any("must not have a `prev`" in p for p in problems)


def test_an_unknown_kind_stops_further_field_checks():
    """Field rules are per kind, so an unknown kind has no rules to check against."""
    problems = annotationProblems(0, note(kind="tweaked"))
    assert len(problems) == 1 and "'tweaked'" in problems[0]


def test_a_problem_says_where_to_look():
    problems = annotationProblems(2, note(path="billing/invoices.py", line=84, title=""))
    assert "annotations[2] (billing/invoices.py:84)" in problems[0]


def test_a_rejection_tells_the_agent_what_to_do_next():
    """A list of faults an agent cannot act on is a dead end, not a gate."""
    text = rejection(validate(review(intent="")))
    assert "tony_publish again with the same sessionId" in text
    assert "1 problem" in text


# --- starting --------------------------------------------------------------

def test_start_refuses_before_the_agent_spends_a_context(tmp_path, monkeypatch):
    """Learning there is nowhere to publish after writing the review is too late."""
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: None)
    out = startReview(str(makeRepo(tmp_path)))
    assert "not logged in" in out and "Do not write the review" in out


def test_start_refuses_a_dirty_tree(tmp_path, monkeypatch):
    """Rendered code is read from disk; uncommitted edits make those lines lie."""
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    repo = makeRepo(tmp_path)
    (repo / "f.txt").write_text("two\n")
    assert "uncommitted changes" in startReview(str(repo))


def test_start_refuses_an_empty_range(tmp_path, monkeypatch):
    """An already-merged branch is the common typo, and it looks like success."""
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    repo = makeRepo(tmp_path)
    assert "no changes to review" in startReview(str(repo), "main...HEAD")


def test_start_hands_back_the_served_document_and_the_diff(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    monkeypatch.setattr(mcp_server.hosted, "fetchInstructions",
                        lambda: ({"version": "abc123", "document": "WRITE IT LIKE THIS"}, None))
    repo = makeRepo(tmp_path)
    (repo / "f.txt").write_text("two\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", "c2"], check=True)

    out = startReview(str(repo), "HEAD~1...HEAD")
    assert "WRITE IT LIKE THIS" in out
    assert "diff --git" in out

    sid = out.split("sessionId: ", 1)[1].split("\n", 1)[0]
    assert mcp_server.SESSIONS[sid]["instructions"] == "abc123"


def test_start_does_not_fall_back_to_a_stale_document(tmp_path, monkeypatch):
    """The document and the validator are one contract; a guess at it is not."""
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    monkeypatch.setattr(mcp_server.hosted, "fetchInstructions",
                        lambda: (None, "could not reach the site"))
    repo = makeRepo(tmp_path)
    (repo / "f.txt").write_text("two\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", "c2"], check=True)

    out = startReview(str(repo), "HEAD~1...HEAD")
    assert "could not fetch the review instructions" in out
    assert not mcp_server.SESSIONS


# --- the parse boundary ----------------------------------------------------

def test_publish_builds_a_payload_that_kept_the_review(tmp_path, monkeypatch):
    """The API path finds its review inside a fence; this one is handed an object.

    Feeding a dict through the fence parser returns nothing and publishes a page
    with a diff and no annotations — which reads as a review that found nothing
    to say, at exit 0.
    """
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    monkeypatch.setattr(mcp_server.hosted, "fetchInstructions",
                        lambda: ({"version": "v1", "document": "DOC"}, None))
    repo = makeRepo(tmp_path)
    (repo / "f.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", "c2"], check=True)

    published = {}
    monkeypatch.setattr(mcp_server.hosted, "publish",
                        lambda body, **kw: (published.update(json.loads(body)) or
                                            ("https://tony-cli.com/r/x", None)))

    out = startReview(str(repo), "HEAD~1...HEAD")
    sid = out.split("sessionId: ", 1)[1].split("\n", 1)[0]
    written = review(annotations=[note(path="f.txt", line=2, kind="added",
                                       now="Adds a second line.")])
    assert "Published:" in mcp_server.publishReview(written, sid)

    assert published["intent"] == "Does a thing."
    assert len(published["annotations"]) == 1
    assert published["coverage"]["unexplainedLines"] == 0
    assert published["instructions"] == "v1"
