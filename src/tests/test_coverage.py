"""Where notes land, and what counts as unexplained.

Both of these are the deterministic layer refusing to take the model's word for
something the diff already knows. Placement used to come from the line the model
named, which put a note describing lines 250-278 in the middle of the block it
described. Coverage was never computed at all, so a review that explained two
thirds of a diff rendered exactly like one that explained all of it.
"""

from tony_cli.layout import changedRuns, layout, runCoverage


def hunk(start, added, tail=True):
    body = f"@@ -{start},3 +{start},{added} @@ ctx\n"
    body += "".join(f"+    line {n}\n" for n in range(start, start + added))
    return body + ("     tail\n" if tail else "")


def note(line, kind="changed", n=0):
    return {"k": "note", "n": n, "data": {"line": line, "kind": kind}}


def rowAfter(blocks, i):
    """The first diff row following block i — what the note visually sits above."""
    for b in blocks[i + 1:]:
        if b["k"] == "row":
            return b
    return None


# --- placement -------------------------------------------------------------

def test_note_lands_at_the_start_of_the_run_it_describes():
    """A line named mid-block splits the block. The span already knows better."""
    body = hunk(250, 29)
    blocks = layout(body, [note(263)])
    at = next(i for i, b in enumerate(blocks) if b["k"] == "note")
    assert blocks[at]["span"][:2] == [250, 278]
    assert rowAfter(blocks, at)["g"] == 250


def test_a_note_already_at_the_start_does_not_move():
    blocks = layout(hunk(250, 29), [note(250)])
    at = next(i for i, b in enumerate(blocks) if b["k"] == "note")
    assert rowAfter(blocks, at)["g"] == 250


def test_notes_on_different_runs_stay_on_their_own_runs():
    body = hunk(10, 2) + hunk(250, 29)
    blocks = layout(body, [note(263, n=0), note(11, n=1)])
    placed = {
        b["n"]: rowAfter(blocks, i)["g"]
        for i, b in enumerate(blocks) if b["k"] == "note"
    }
    assert placed == {0: 250, 1: 10}


def test_a_line_outside_every_run_keeps_the_model_s_position():
    """No run to snap to, so there is nothing better than what was named."""
    blocks = layout(hunk(10, 2), [note(999)])
    assert any(b["k"] == "note" for b in blocks)


# --- coverage --------------------------------------------------------------

def test_every_run_is_counted():
    body = hunk(10, 2) + hunk(250, 29)
    runs, missed = runCoverage(body, [])
    assert len(runs) == 2
    assert missed == runs  # nothing explained anything


def test_an_annotation_covers_the_whole_run_not_one_line():
    body = hunk(250, 29)
    runs, missed = runCoverage(body, [note(263)])
    assert missed == []


def test_unexplained_runs_become_gap_blocks_at_their_own_start():
    body = hunk(10, 2) + hunk(250, 29)
    blocks = layout(body, [note(263)])
    gaps = [(i, b) for i, b in enumerate(blocks) if b["k"] == "gap"]
    assert len(gaps) == 1
    i, gap = gaps[0]
    assert gap["span"][:2] == [10, 11]
    assert rowAfter(blocks, i)["g"] == 10


def test_a_fully_explained_file_has_no_gaps():
    body = hunk(10, 2) + hunk(250, 29)
    blocks = layout(body, [note(10, n=0), note(263, n=1)])
    assert not [b for b in blocks if b["k"] == "gap"]


def test_replacements_count_as_runs_too():
    """Behaviour changes are exactly what must not go unexplained."""
    body = "@@ -10,2 +10,2 @@ ctx\n-    old\n+    new\n     tail\n"
    runs, missed = runCoverage(body, [])
    assert len(runs) == 1 and runs[0][2] is True   # hadDeletion
    assert len(missed) == 1


def test_a_risk_alone_does_not_explain_a_run():
    """Risks sit behind a toggle and are not the explanation. Only notes cover.

    This used to pass with `missed == []`, which made "warn about it" a way to
    satisfy coverage without ever saying what the code did — and once coverage
    became a publish gate, the cheapest way through it.
    """
    body = hunk(250, 29)
    risk = {"k": "risk", "n": 0, "data": {"line": 263}}
    runs, missed = runCoverage(body, [risk])
    assert missed == runs


def test_a_skip_accounts_for_a_run_it_declines_to_explain():
    """The escape hatch for a run that genuinely needs no prose — generated
    output, a mechanical rename. It covers, because it is an answer."""
    body = hunk(250, 29)
    skip = {"k": "skip", "n": 0, "data": {"line": 263, "why": "generated"}}
    runs, missed = runCoverage(body, [skip])
    assert missed == []


def test_several_notes_on_one_run_keep_their_own_positions():
    """An added file is a single run from line 1 to its end.

    The notes inside it describe different parts of it, and snapping them to the
    run's start would stack three explanations on line 1 and throw away the only
    positional information the review has. Real reviews of this repo hit this on
    every new file — one had three notes inside a 532-line run.
    """
    body = hunk(1, 60, tail=False)
    blocks = layout(body, [note(5, n=0), note(30, n=1), note(55, n=2)])
    placed = {
        b["n"]: rowAfter(blocks, i)["g"]
        for i, b in enumerate(blocks) if b["k"] == "note"
    }
    assert placed == {0: 5, 1: 30, 2: 55}


def test_a_sole_note_still_snaps_when_others_are_on_different_runs():
    body = hunk(10, 2) + hunk(250, 29)
    blocks = layout(body, [note(11, n=0), note(263, n=1)])
    placed = {
        b["n"]: rowAfter(blocks, i)["g"]
        for i, b in enumerate(blocks) if b["k"] == "note"
    }
    assert placed == {0: 10, 1: 250}
