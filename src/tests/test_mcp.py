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
from tony_cli.anchors import anchorProblems
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


# --- connecting to a harness -----------------------------------------------

def test_connect_merges_into_an_existing_config(tmp_path, monkeypatch):
    """These files hold the user's other servers; a rewrite that dropped them
    would be a worse bug than failing to connect."""
    from tony_cli import mcp_config

    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    state, _ = mcp_config.connectJson(str(config), ["mcpServers"], "/bin/tony")

    body = json.loads(config.read_text())
    assert state == "wrote"
    assert body["theme"] == "dark"
    assert body["mcpServers"]["other"] == {"command": "x"}
    assert body["mcpServers"]["tony"] == {"command": "/bin/tony", "args": ["mcp"]}

    # Running it twice must not append a second entry or rewrite the first.
    assert mcp_config.connectJson(str(config), ["mcpServers"], "/bin/tony")[0] == "already"


def test_connect_keeps_codex_comments(tmp_path, monkeypatch):
    """Codex's config is hand-edited TOML. Parsing and re-emitting would work,
    and would silently strip every comment in it."""
    from tony_cli import mcp_config

    config = tmp_path / "config.toml"
    config.write_text('# my notes\nmodel = "gpt-5"\n')
    monkeypatch.setattr(mcp_config, "CODEX", str(config))

    assert mcp_config.connectCodex("/bin/tony")[0] == "wrote"
    text = config.read_text()
    assert "# my notes" in text and 'model = "gpt-5"' in text
    assert text.count("[mcp_servers.tony]") == 1

    assert mcp_config.connectCodex("/bin/tony")[0] == "already"
    assert config.read_text().count("[mcp_servers.tony]") == 1


def test_install_points_at_connect():
    """`tony install` is the obvious wrong guess — tony is already installed."""
    from tony_cli.agent import main

    assert main(["install"]) == 2


# --- what the agent is handed vs what the page is built from ---------------

def test_generated_bodies_are_stripped_for_the_agent_only(tmp_path, monkeypatch):
    """A lockfile costs the reviewer's context and earns no annotation. The
    page still has to show it changed, with its real line counts."""
    from tony_cli.source.local import splitDiffByFile, withoutGeneratedBodies

    lock = "".join(f"+  \"dep-{n}\": \"1.0.{n}\",\n" for n in range(200))
    diff = (
        "diff --git a/src/app.ts b/src/app.ts\n"
        "index 111..222 100644\n--- a/src/app.ts\n+++ b/src/app.ts\n"
        "@@ -1,2 +1,3 @@\n ctx\n+const x = 1;\n"
        "diff --git a/package-lock.json b/package-lock.json\n"
        "index 333..444 100644\n--- a/package-lock.json\n+++ b/package-lock.json\n"
        f"@@ -1,1 +1,200 @@\n{lock}"
    )

    stripped = withoutGeneratedBodies(diff)
    assert len(stripped) < len(diff) / 10
    assert "const x = 1;" in stripped          # the real change survives
    assert "dep-100" not in stripped           # the lockfile body does not
    assert "package-lock.json" in stripped     # but the file is still named

    # The page is laid out from the untouched diff, so counts stay right.
    byPath = {f["path"]: f for f in splitDiffByFile(diff)}
    assert byPath["package-lock.json"]["additions"] == 200


def test_build_output_is_skippable_by_directory():
    from tony_cli.layout import isSkippable

    assert isSkippable("dist/bundle.js")
    assert isSkippable("web/node_modules/pkg/index.js")
    assert isSkippable("src/__pycache__/mod.pyc")
    # A source file whose name merely contains one of them is not build output.
    assert not isSkippable("src/distance.py")
    assert not isSkippable("src/builder.ts")


def test_the_agent_gets_whole_functions_without_moving_any_line(tmp_path, monkeypatch):
    """`-W` grows each hunk to its enclosing function — the thing an agent
    opens the file for. It must not move what counts as a changed line, or
    every annotation anchor and the coverage measure shift with it."""
    from tony_cli.layout import changedRuns
    from tony_cli.source.local import getDiff, splitDiffByFile

    # The changed line sits far enough into the function that git's default
    # three lines of context cannot reach the `def` — which is the whole case
    # this exists for, and what a short fixture would hide.
    body = "\n".join(f"    step{n} = {n}" for n in range(12))
    repo = makeRepo(tmp_path)
    (repo / "m.py").write_text(f"def outer():\n{body}\n    return step11\n")
    subprocess.run(["git", "-C", str(repo), "add", "m.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c2"], check=True)
    (repo / "m.py").write_text(
        f"def outer():\n{body.replace('step11 = 11', 'step11 = 99')}\n    return step11\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", "c3"], check=True)

    plain = getDiff(str(repo), "HEAD~1", "HEAD")
    wide = getDiff(str(repo), "HEAD~1", "HEAD", wholeFunctions=True)

    # `def outer():` also appears in git's @@ header as a funcname hint, so the
    # test is whether the function's earlier lines arrive as context.
    assert "step0 = 0" not in plain         # the hunk alone stops well short
    assert "step0 = 0" in wide              # -W reaches back to the whole function

    runs = lambda d: changedRuns(splitDiffByFile(d)[0]["body"])
    assert runs(plain) == runs(wide)


# --- the coverage gate -----------------------------------------------------
#
# The thing that replaced owning the loop. tony controls no model and no
# harness, so what it refuses to publish is the only quality control it has.

def changedRepo(tmp_path):
    """A repo whose HEAD adds one 9-line block and one 40-line generated file."""
    repo = makeRepo(tmp_path)
    (repo / "a.py").write_text(
        "x = 1\n" + "".join(f"def f{n}():\n    return {n}\n\n" for n in range(3)))
    (repo / "gen_pb2.py").write_text("".join(f"FIELD_{n} = {n}\n" for n in range(40)))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c2"], check=True)
    return repo


def started(repo, monkeypatch):
    monkeypatch.setattr(mcp_server.hosted, "savedToken", lambda: "t")
    monkeypatch.setattr(mcp_server.hosted, "fetchInstructions",
                        lambda: ({"version": "v1", "document": "D"}, None))
    monkeypatch.setattr(mcp_server.hosted, "publish",
                        lambda *a, **k: ("https://tony-cli.com/r/x", None))
    out = startReview(str(repo), "HEAD~1...HEAD")
    return out.split("sessionId: ", 1)[1].split("\n", 1)[0]


def test_an_unexplained_block_is_refused_and_named(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview({"intent": "i", "annotations": []}, sid)
    assert "not published" in out
    assert "a.py:1-10" in out and "10 lines" in out
    assert "gen_pb2.py:1-40" in out


def test_a_skip_gets_a_block_past_the_gate(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview({
        "intent": "i",
        "annotations": [note(path="a.py", line=2, kind="added", now="defines three functions")],
        "skips": [{"path": "gen_pb2.py", "line": 1, "why": "generated from schema.proto"}],
    }, sid)
    assert "Published:" in out


def test_a_risk_is_not_an_explanation(tmp_path, monkeypatch):
    """Otherwise "warn about it" is the cheapest way through the gate."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview({
        "intent": "i", "annotations": [],
        "risks": [{"path": "a.py", "line": 2, "text": "might break"}],
        "skips": [{"path": "gen_pb2.py", "line": 1, "why": "generated"}],
    }, sid)
    assert "not published" in out and "a.py:1-10" in out


def test_a_one_line_change_needs_no_prose(tmp_path, monkeypatch):
    """A moved import or a bumped constant is not something to demand a
    paragraph for — a gate that does manufactures the padding it forbids."""
    repo = makeRepo(tmp_path)
    (repo / "f.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", "c2"], check=True)
    sid = started(repo, monkeypatch)
    assert "Published:" in mcp_server.publishReview({"intent": "i", "annotations": []}, sid)


def test_a_skip_needs_a_reason(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview({
        "intent": "i", "annotations": [],
        "skips": [{"path": "gen_pb2.py", "line": 1}],
    }, sid)
    assert "skips[0] has no `why`" in out


def test_the_gate_runs_out_of_patience_but_still_publishes(tmp_path, monkeypatch):
    """The retries are the point — they are what makes an agent go back and
    explain what it skipped. Refusing forever is not: the developer already
    paid for the work, and the page marks every gap it still has, so an honest
    incomplete review beats a message saying they got nothing."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    empty = {"intent": "i", "annotations": []}
    assert "2 attempts left" in mcp_server.publishReview(empty, sid)
    assert "1 attempt left" in mcp_server.publishReview(empty, sid)
    out = mcp_server.publishReview(empty, sid)
    assert "Published:" in out
    assert "still unexplained" in out


def test_skips_reach_the_page_where_the_code_is(tmp_path, monkeypatch):
    """A skip is only worth anything if the reader sees it — that is what
    separates a block that was dismissed from one that was missed."""
    published = {}
    repo = changedRepo(tmp_path)
    sid = started(repo, monkeypatch)
    monkeypatch.setattr(mcp_server.hosted, "publish",
                        lambda body, **kw: (published.update(json.loads(body)) or
                                            ("https://tony-cli.com/r/x", None)))
    mcp_server.publishReview({
        "intent": "i",
        "annotations": [note(path="a.py", line=2, kind="added", now="three functions")],
        "skips": [{"path": "gen_pb2.py", "line": 1, "why": "generated from schema.proto"}],
    }, sid)

    assert published["skips"][0]["why"] == "generated from schema.proto"
    gen = next(f for f in published["files"] if f["path"] == "gen_pb2.py")
    assert any(b["k"] == "skip" for b in gen["blocks"])
    assert not any(b["k"] == "gap" for b in gen["blocks"])


# --- anchors and references ------------------------------------------------
#
# Coverage asks whether the review accounts for the whole diff. These ask the
# other half of the question: whether the places it names exist. Nothing
# downstream catches an invented one — the renderer reads whatever range it is
# given and shows the reader a confident screenful of the wrong code.

def covered(**over):
    """A review that satisfies coverage on `changedRepo`, plus whatever is under test."""
    return {
        "intent": "i",
        "annotations": [note(path="a.py", line=2, now="defines three functions")],
        "skips": [{"path": "gen_pb2.py", "line": 1, "why": "generated from schema.proto"}],
        **over,
    }


def test_an_annotation_on_a_file_outside_the_diff_is_refused(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(annotations=[
        note(path="a.py", line=2, now="defines three functions"),
        note(path="src/a.py", line=4, now="the same thing again"),
    ]), sid)
    assert "not published" in out
    assert "src/a.py" in out
    # A basename that matches exactly one changed file is nearly always the
    # miss, and naming it makes the fix one token.
    assert "Did you mean a.py?" in out


def test_an_anchor_outside_the_changed_region_is_refused(tmp_path, monkeypatch):
    """The failure that put annotations on the wrong code: a line number that
    resolves to nothing, which coverage can only report as a different gap."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(annotations=[
        note(path="a.py", line=2, now="defines three functions"),
        note(path="a.py", line=400, now="something down here"),
    ]), sid)
    assert "a.py:400" in out
    assert "between 1 and 10" in out


def test_an_anchor_above_its_block_resolves_forward(tmp_path, monkeypatch):
    """The page takes an anchor to the run containing it, or to the next one
    down the file. This module has to allow exactly what that resolves, or an
    agent gets rejected for a gap somewhere else entirely."""
    diff = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -20,3 +20,4 @@\n context\n+added\n context\n context\n"
    )
    above = {"annotations": [note(path="m.py", line=12)]}
    inside = {"annotations": [note(path="m.py", line=21)]}
    below = {"annotations": [note(path="m.py", line=99)]}

    assert anchorProblems(above, diff, str(tmp_path)) == []
    assert anchorProblems(inside, diff, str(tmp_path)) == []
    assert "past the last changed line" in anchorProblems(below, diff, str(tmp_path))[0]


def test_an_impact_inside_the_diff_is_refused(tmp_path, monkeypatch):
    """A changed file is explained by its own annotations. Listing it as blast
    radius is a way to look thorough without leaving the diff."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(impacts=[{
        "symbol": "f0", "fromPath": "a.py", "path": "a.py", "line": 2,
        "kind": "compatible", "why": "calls it",
    }]), sid)
    assert "is in the diff" in out


def test_an_impact_on_a_file_that_does_not_exist_is_refused(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(impacts=[{
        "symbol": "f0", "fromPath": "a.py", "path": "dashboard/api.ts", "line": 112,
        "kind": "breaks", "why": "calls f0 with the old signature",
    }]), sid)
    assert "not a file in this repository" in out


def test_an_impact_past_the_end_of_a_real_file_is_refused(tmp_path, monkeypatch):
    """f.txt is one line long. Line 112 is a line the agent did not read."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(impacts=[{
        "symbol": "f0", "fromPath": "a.py", "path": "f.txt", "line": 112,
        "kind": "behavior-change", "why": "reads the value",
    }]), sid)
    assert "f.txt:112" in out and "1 lines long" in out


def test_an_impact_whose_symbol_comes_from_nowhere_is_refused(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(impacts=[{
        "symbol": "f0", "fromPath": "billing/invoices.py", "path": "f.txt",
        "line": 1, "kind": "compatible", "why": "reads the value",
    }]), sid)
    assert "not a changed file" in out


def test_a_real_impact_publishes(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(impacts=[{
        "symbol": "f0", "fromPath": "a.py", "path": "f.txt", "line": 1,
        "kind": "compatible", "why": "reads the value and is unaffected",
    }]), sid)
    assert "Published:" in out


def test_a_walkthrough_step_past_the_end_of_a_file_is_refused(tmp_path, monkeypatch):
    """The page reads these exact lines off disk. A range past the end renders
    as an empty box under a confident sentence."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(walkthroughs=[{
        "reach": "changed", "title": "T", "trigger": "You run it",
        "whatChanged": "It now returns.",
        "steps": [
            {"say": "It starts.", "path": "f.txt", "lines": [1, 1]},
            {"say": "It reads on.", "path": "f.txt", "lines": [40, 90]},
            {"say": "It finishes."},
        ],
    }]), sid)
    assert "f.txt:40-90" in out and "1 lines long" in out


def test_a_walkthrough_that_is_not_a_trace_is_refused(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(walkthroughs=[{
        "reach": "changed", "title": "T", "trigger": "You run it",
        "whatChanged": "It now returns.",
        "steps": [{"say": "It runs."}],
    }]), sid)
    assert "1 steps" in out and "3 to 7" in out


def test_a_traced_walkthrough_publishes(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(walkthroughs=[{
        "reach": "changed", "title": "T", "trigger": "You run it",
        "whatChanged": "It now returns.",
        "steps": [
            {"say": "It starts.", "path": "f.txt", "lines": [1, 1], "phase": "same"},
            {"say": "It calls the new function.", "path": "a.py", "lines": [2, 3],
             "state": {"n": "0 -> 1"}, "phase": "new"},
            {"say": "It finishes.", "phase": "same"},
        ],
    }]), sid)
    assert "Published:" in out


def test_a_mirror_note_must_point_at_a_real_copy(tmp_path, monkeypatch):
    """The mirror annotation is the one that explains nothing itself. If where
    it sends the reader is not in the change, that code is explained by nobody."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    out = mcp_server.publishReview(covered(annotations=[
        note(path="a.py", line=2, now="defines three functions"),
        note(path="a.py", line=4, title="Same change, async copy",
             now="Mirrors src/async_a.py line for line. Read the annotations there."),
    ]), sid)
    assert "src/async_a.py" in out
    assert "not in this change" in out


# --- provenance ------------------------------------------------------------
#
# tony controls no model and no loop, so the only way to learn which agents
# write reviews worth reading is to record what wrote each one next to the
# coverage it achieved.

def capturePublish(monkeypatch):
    """The uploaded payload, parsed. Install after `started`, which patches it too."""
    sent = {}
    monkeypatch.setattr(mcp_server.hosted, "publish",
                        lambda payload, **k: (sent.update(json.loads(payload)),
                                              ("https://tony-cli.com/r/x", None))[1])
    return sent


def test_the_payload_records_what_wrote_the_review(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    sent = capturePublish(monkeypatch)
    mcp_server.SESSIONS[sid]["harness"] = ("claude-code", "2.1.0")

    out = mcp_server.publishReview(covered(), sid, model="claude-opus-5")
    assert "Published:" in out

    from_ = sent["provenance"]
    assert from_["harness"] == "claude-code"
    assert from_["harnessVersion"] == "2.1.0"
    assert from_["model"] == "claude-opus-5"
    assert from_["retries"] == 0
    assert from_["diffFiles"] == 2
    assert from_["diffLines"] > 0
    assert from_["seconds"] >= 0
    # Which document produced it, alongside — the pair is what makes "did
    # tightening the instructions help" answerable at all.
    assert sent["instructions"] == "v1"


def test_provenance_counts_the_retries_the_gate_forced(tmp_path, monkeypatch):
    sid = started(changedRepo(tmp_path), monkeypatch)
    sent = capturePublish(monkeypatch)

    mcp_server.publishReview({"intent": "i", "annotations": []}, sid)
    mcp_server.publishReview(covered(), sid)

    assert sent["provenance"]["retries"] == 1


def test_an_agent_that_does_not_know_its_model_still_publishes(tmp_path, monkeypatch):
    """Blank is a real answer. Guessing would poison the one column that says
    which model wrote what."""
    sid = started(changedRepo(tmp_path), monkeypatch)
    sent = capturePublish(monkeypatch)

    assert "Published:" in mcp_server.publishReview(covered(), sid)
    assert sent["provenance"]["model"] == ""
    assert sent["provenance"]["harness"] == ""


def test_a_harness_that_will_not_identify_itself_is_not_an_error():
    """Reaching through three layers of SDK object for a diagnostic field must
    never be the reason a review fails to publish."""
    class Nothing:
        pass

    assert mcp_server.harnessOf(None) == ("", "")
    assert mcp_server.harnessOf(Nothing()) == ("", "")
