"""The pure functions behind the page.

These decide which line numbers the reader is shown. `codeWindow` silently
showing the wrong lines is the failure that would quietly destroy trust in a
walkthrough, so the off-by-one edges are pinned here.
"""

import textwrap

from tony.render import changedRuns, codeWindow, kindFor, spanFor
from tony.source.local import splitDiffByFile


def body(text):
    return textwrap.dedent(text).strip("\n")


# --- changedRuns -----------------------------------------------------------

def test_replacement_run_spans_the_new_lines():
    runs = changedRuns(body("""
        @@ -1,4 +1,5 @@
         a
        -b
        +B
        +C
         d
    """))
    assert runs == [(2, 3, True)]


def test_deletion_only_collapses_to_one_position():
    # Removed lines occupy no line in the new file, so the run marks where they were.
    runs = changedRuns(body("""
        @@ -1,3 +1,2 @@
         a
        -b
         c
    """))
    assert runs == [(2, 2, True)]


def test_pure_insertion_is_marked_as_having_no_deletion():
    # The httpx case: a guard inserted ahead of code that stayed exactly as it was.
    runs = changedRuns(body("""
        @@ -1,3 +1,5 @@
         a
        +guard
        +return
         b
    """))
    assert runs == [(2, 3, False)]


def test_deletion_after_additions_still_marks_the_run():
    runs = changedRuns(body("""
        @@ -1,3 +1,3 @@
         a
        +B
        -b
         c
    """))
    assert runs == [(2, 2, True)]


def test_context_between_edits_splits_the_runs():
    runs = changedRuns(body("""
        @@ -1,5 +1,5 @@
        +x
         a
         b
        +y
         c
    """))
    assert runs == [(1, 1, False), (4, 4, False)]


def test_deletion_flag_does_not_leak_across_runs():
    runs = changedRuns(body("""
        @@ -1,5 +1,5 @@
         a
        -b
        +B
         c
        +d
         e
    """))
    assert runs == [(2, 2, True), (4, 4, False)]


def test_run_open_at_the_end_of_a_hunk_is_still_recorded():
    runs = changedRuns(body("""
        @@ -1,2 +1,3 @@
         a
        +b
        +c
    """))
    assert runs == [(2, 3, False)]


def test_run_is_closed_at_a_hunk_boundary():
    runs = changedRuns(body("""
        @@ -1,2 +1,3 @@
         a
        +b
        @@ -20,2 +21,3 @@
         z
        +y
    """))
    assert runs == [(2, 2, False), (22, 22, False)]


def test_no_hunk_header_means_no_runs():
    assert changedRuns("") == []
    assert changedRuns(" a\n+b") == []


# --- spanFor ---------------------------------------------------------------

def test_span_containing_the_anchor_wins():
    assert spanFor(5, [(2, 3, False), (4, 8, True), (12, 14, False)]) == (4, 8, True)


def test_anchor_before_every_run_takes_the_next_one():
    assert spanFor(1, [(4, 8, True), (12, 14, False)]) == (4, 8, True)


def test_anchor_in_a_gap_takes_the_following_run():
    assert spanFor(10, [(4, 8, True), (12, 14, False)]) == (12, 14, False)


def test_anchor_past_the_last_run_falls_back_to_itself():
    assert spanFor(99, [(4, 8, True)]) == (99, 99, False)


def test_boundaries_are_inclusive():
    assert spanFor(4, [(4, 8, True)]) == (4, 8, True)
    assert spanFor(8, [(4, 8, True)]) == (4, 8, True)


# --- kindFor ---------------------------------------------------------------

def test_claimed_changed_over_a_pure_insertion_becomes_added():
    # The httpx bug: an inserted guard labelled "changed" with nothing to compare against.
    assert kindFor("changed", (35, 40, False)) == "added"


def test_claimed_changed_over_a_replacement_stays_changed():
    assert kindFor("changed", (35, 40, True)) == "changed"


def test_claimed_added_over_a_replacement_is_corrected():
    assert kindFor("added", (35, 40, True)) == "changed"


def test_removed_is_never_rewritten():
    assert kindFor("removed", (43, 43, True)) == "removed"
    assert kindFor("removed", (43, 43, False)) == "removed"


def test_missing_span_leaves_the_claim_alone():
    assert kindFor("changed", None) == "changed"
    assert kindFor("added", None) == "added"


def test_missing_kind_defaults_without_a_span():
    assert kindFor(None, None) == "changed"


# --- codeWindow ------------------------------------------------------------

def writeSrc(tmp_path, name="a.py", n=20):
    (tmp_path / name).write_text("\n".join(f"line{i}" for i in range(1, n + 1)))
    return name


def gutters(htmlOut):
    import re
    return [int(m) for m in re.findall(r'<span class="g">(\d+)</span>', htmlOut)]


def test_window_pads_two_lines_either_side(tmp_path):
    name = writeSrc(tmp_path)
    out = codeWindow(str(tmp_path), name, [10, 12])
    assert gutters(out) == [8, 9, 10, 11, 12, 13, 14]


def test_requested_lines_are_the_hot_ones(tmp_path):
    name = writeSrc(tmp_path)
    out = codeWindow(str(tmp_path), name, [10, 12])
    hot = [
        int(n) for n in __import__("re").findall(
            r'<div class="l c hot"><span class="g">(\d+)</span>', out
        )
    ]
    assert hot == [10, 11, 12]


def test_line_numbers_match_the_source_text(tmp_path):
    name = writeSrc(tmp_path)
    out = codeWindow(str(tmp_path), name, [10, 10])
    # The gutter number and the text on that row must agree — this is the trust bug.
    assert '<span class="g">10</span>line10' in out


def test_single_line_step_is_accepted(tmp_path):
    name = writeSrc(tmp_path)
    assert gutters(codeWindow(str(tmp_path), name, [3])) == [1, 2, 3, 4, 5]


def test_window_clamps_at_the_top_of_the_file(tmp_path):
    name = writeSrc(tmp_path)
    assert gutters(codeWindow(str(tmp_path), name, [1, 2])) == [1, 2, 3, 4]


def test_window_clamps_at_the_end_of_the_file(tmp_path):
    name = writeSrc(tmp_path, n=20)
    assert gutters(codeWindow(str(tmp_path), name, [19, 20])) == [17, 18, 19, 20]


def test_range_past_the_end_of_the_file_does_not_invent_lines(tmp_path):
    name = writeSrc(tmp_path, n=20)
    assert gutters(codeWindow(str(tmp_path), name, [18, 40])) == [16, 17, 18, 19, 20]


def test_missing_file_says_so_instead_of_raising(tmp_path):
    out = codeWindow(str(tmp_path), "nope.py", [1, 2])
    assert "could not read" in out


def test_no_path_means_outside_the_codebase(tmp_path):
    assert "outside the codebase" in codeWindow(str(tmp_path), None, None)


# --- splitDiffByFile -------------------------------------------------------

MODIFIED = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = 3
"""

ADDED = """diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+one
+two
"""

DELETED = """diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 4444444..0000000
--- a/gone.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-bye
"""

RENAMED = """diff --git a/old/name.ts b/new/name.ts
similarity index 90%
rename from old/name.ts
rename to new/name.ts
--- a/old/name.ts
+++ b/new/name.ts
@@ -1,1 +1,1 @@
-a
+b
"""

BINARY = """diff --git a/img.png b/img.png
index 5555555..6666666 100644
Binary files a/img.png and b/img.png differ
"""


def test_empty_diff_is_no_files():
    assert splitDiffByFile("") == []
    assert splitDiffByFile("\n  \n") == []


def test_modified_file_counts_and_body():
    (f,) = splitDiffByFile(MODIFIED)
    assert f["path"] == "src/app.py"
    assert f["oldPath"] is None
    assert f["status"] == "modified"
    assert (f["additions"], f["deletions"]) == (2, 1)
    assert f["body"].startswith("@@ -1,3 +1,4 @@")
    assert "+++" not in f["body"]


def test_statuses_are_read_from_the_header():
    assert splitDiffByFile(ADDED)[0]["status"] == "added"
    assert splitDiffByFile(DELETED)[0]["status"] == "deleted"
    assert splitDiffByFile(RENAMED)[0]["status"] == "renamed"


def test_rename_keeps_the_old_path():
    (f,) = splitDiffByFile(RENAMED)
    assert (f["oldPath"], f["path"]) == ("old/name.ts", "new/name.ts")


def test_binary_file_has_no_body():
    (f,) = splitDiffByFile(BINARY)
    assert f["binary"] is True
    assert f["body"] == ""
    assert (f["additions"], f["deletions"]) == (0, 0)


def test_multiple_files_split_cleanly():
    files = splitDiffByFile(MODIFIED + ADDED + BINARY)
    assert [f["path"] for f in files] == ["src/app.py", "new.txt", "img.png"]


def test_a_diff_line_inside_a_body_does_not_start_a_new_file():
    # A removed line whose text happens to begin with "diff --git" must stay in the body.
    diff = MODIFIED.replace("-x = 1", "-x = 1\n-diff --git a/fake b/fake")
    files = splitDiffByFile(diff)
    assert [f["path"] for f in files] == ["src/app.py"]
