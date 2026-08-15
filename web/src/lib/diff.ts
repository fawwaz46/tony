/**
 * Presentation helpers only.
 *
 * Nothing here decides anything. Line numbers, spans, and the added/changed/
 * removed tag are all resolved in Python by `layout()` in src/tony/render.py
 * and arrive in the payload already settled — see DESIGN.md, "Ground truth".
 * If you find yourself re-deriving a line number here, the fix belongs in the
 * payload, not in this file.
 */

export type Span = [start: number, end: number, hadDeletion: boolean];

export type Row = { k: "row"; cls: "a" | "d" | "c" | "h"; g: number | null; text: string };
export type NoteRef = { k: "note" | "risk"; n: number; span: Span | null; tag: string };
export type Block = Row | NoteRef;

/** 'lines 14–18' / 'line 14' — tells the reader which lines the note is about. */
export function lineLabel(span: Span | null): string {
  if (!span) return "";
  const [start, end] = span;
  return start === end ? `line ${start}` : `lines ${start}–${end}`;
}

export const KIND_LABEL: Record<string, string> = {
  breaks: "Breaks",
  "behavior-change": "Behaves differently",
  compatible: "Compatible",
};

export const KIND_ORDER: Record<string, number> = {
  breaks: 0,
  "behavior-change": 1,
  compatible: 2,
};

export const PHASE_LABEL: Record<string, string> = {
  new: "new",
  changed: "changed",
  removed: "no longer happens",
  same: "",
};

export const fileId = (path: string) => path.replace(/[^A-Za-z0-9]/g, "_");
