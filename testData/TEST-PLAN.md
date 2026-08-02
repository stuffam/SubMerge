# SubMerge Test Data — Test Plan

A fixture set for exercising every SubMerge feature, setting, and documented
limitation. Every behavior claimed below has been verified directly against
the plugin's own comparison engine — none of it is guesswork.

Default settings assumed unless a step says otherwise:
`ignore_line_endings: true`, `compare_metadata: false`, `detect_moved_lines: true`,
`highlight_changed_line: auto`, `intraline_mode: word`,
`graduated_inline_highlight: true`, `csv_table_view: false`.

---

## 1. `01-basic-file-diff/` — the fundamentals

**`two-way/original.txt` vs `modified.txt`**
Compare Selected Files (or tabs). Expect:
- `retry_attempts = 3` — a genuinely new line → **green**, no counterpart on
  the other side.
- `server_port = 8080` → `9090` and `debug_mode = false` → `true` — each line
  exists on both sides but differs → only the changed value highlights
  (orange), not the whole line. See §6 for why it's never the whole line
  under `auto`.
- `max_connections` and the surrounding lines are untouched.

**`three-way/version-A/B/C.txt`**
Select all three, compare. Pane A is the base both B and C are diffed
against. Try **Copy Difference To…** on a 3-pane difference — it should ask
which pane to send it to rather than guessing.

**`identical/file-a.txt` / `file-b.txt`**
Byte-identical. Expect a dialog saying so, with **no comparison tabs opened**.
This is the one pair in this set that should never actually open a
side-by-side view.

---

## 2. `02-line-endings/` — CRLF vs LF vs mixed

**`windows.txt` (CRLF) vs `unix.txt` (LF)**, same text otherwise.
- With `ignore_line_endings: true` (default): **identical**, dialog only.
- Turn it **off**: every line shows as different, purely because of the line
  ending. This is the single most common false-alarm SubMerge is built to
  prevent — if you ever see "everything is different" on a real file pair,
  check this setting first.

**`mixed-eol.txt`** alternates CRLF and LF within one file — useful for the
metadata report's `line_endings` field, which should read `mixed (CRLF, LF)`
rather than picking one. Compare it against either of the other two with
**Compare File Metadata** on.

---

## 3. `03-whitespace-and-case/` — the "ignore" settings

| Pair | Setting to test | Expect |
|---|---|---|
| `whitespace-a.js` / `-b.js` | `ignore_all_whitespace` | Different by default; identical with the setting on |
| `case-a.txt` / `-b.txt` | `ignore_case` | Different by default; identical with the setting on |
| `blank-lines-a.txt` / `-b.txt` | `ignore_blank_lines` | Different by default; identical with the setting on |

Toggle each from **Tools → SubMerge → Comparison Options** and re-run the
comparison (or just open it fresh) to see the difference. Each pair changes
only the one thing named — good for confirming a setting does exactly what
it claims and nothing else.

---

## 4. `04-moved-lines/`

`moved-a.txt` / `moved-b.txt`: two whole functions change position between
files (`validate_config()` moves up, `save_config()` moves to the end).

- With `detect_moved_lines: true` (default): the relocated lines highlight
  **blue**, not red/green. Put your cursor on one and press
  **Ctrl+Alt+J** (Cmd+Alt+J) — it should jump to where that block ended up in
  the other pane.
- Turn `detect_moved_lines` off: the same lines now show as a plain
  delete-in-A / add-in-B (red gap + green), with no jump target.

Matching is exact — a moved line that was *also* edited won't be detected as
moved, it'll show as a delete plus an add. This fixture doesn't include that
case deliberately, so you're seeing the clean/ideal case first; edit one
line inside a moved block yourself afterward to see the exact-match
limitation in action.

---

## 5. `05-inline-intensity/`

`minor-major-a.txt` / `-b.txt`:
- Line 1: `jumps` → `leaps`, a small one-word edit. **Orange** (minor).
- Line 3: almost the entire sentence rewritten. **Red** (major).

This is `graduated_inline_highlight` (default on) with the default
`inline_intensity_threshold: 0.4`. Turn `graduated_inline_highlight` off and
both lines should highlight the same shade of orange, losing the distinction.
Try lowering `inline_intensity_threshold` to something like `0.1` — line 1's
small edit should then also escalate to red.

---

## 6. `06-highlight-changed-line-modes/` — read this one before assuming

`partial-match-a.txt` / `-b.txt` has one line per case: a small value change,
a bigger value change, and a line with **zero** shared characters with its
counterpart (`9876543210 !@#$%^&*()` vs `qwertyuiop []{}<>?/`).

**Verified finding, not obvious from the setting's name:** with the default
`intraline_mode: word` (or `char`), `highlight_changed_line: auto` **never**
paints a matched line's full-line yellow background — not even for the
completely-unrelated third line. The intra-line diff always finds *some*
character range to mark as changed (even if that range is the entire line),
so `auto` always takes the "highlight just the changed part" branch. In
practice, `auto` and `never` look identical for any line that has a
counterpart on the other side; the difference between them only shows up for
edge cases this fixture doesn't happen to hit.

To actually see the full-line yellow (`region.yellowish`) highlight on a
*matched* line, you need one of:

- `highlight_changed_line: always` — forces it in addition to the inline
  color, on every differing line.
- `intraline_mode: none` — turns off character-level diffing entirely, so
  every differing line falls back to a plain full-line highlight and the
  orange/red inline colors disappear completely.

Try all three combinations on this same file pair and compare what you see.

---

## 7. `07-csv-tsv-tables/`

Turn on **Show CSV/TSV Files as Tables** first, then compare each pair:

- **`simple.csv` / `simple-modified.csv`** — a changed cell and an added row;
  the baseline "does this even work" case.
- **`quoted-commas-a.csv` / `-b.csv`** — addresses contain commas inside
  quoted fields. The comma inside `"123 Main St, Suite 400"` must not be
  read as a column break.
- **`embedded-newlines-a.csv` / `-b.csv`** — one field contains a real line
  break inside its quotes. The table renderer should keep it as one cell
  spanning multiple wrapped lines, not split it into extra rows.
- **`ragged-rows-a.csv` / `-b.csv`** — row 2 has fewer columns than the
  header, row 3 has more. Confirms short rows don't crash the aligner and
  extra columns don't silently vanish.
- **`data.tsv` / `data-modified.tsv`** — same idea, tab-delimited. Confirms
  delimiter auto-detection picks tabs correctly rather than defaulting to
  comma.

Remember table view is read-only by design — the copy-difference commands
should refuse with a clear message, not silently do nothing. Turn the option
back off afterward to confirm the same files compare normally as plain text.

---

## 8. `08-encoding-and-bom/`

`utf8-no-bom.txt`, `utf8-with-bom.txt` (identical text, one has a UTF-8 BOM
prefix), and `ascii-plain.txt` (same text, ASCII-safe substitutions for the
accented characters).

With **Compare File Metadata** on, compare `utf8-no-bom.txt` against
`utf8-with-bom.txt`: content should read as identical (the BOM isn't counted
as a text difference), but the metadata report's `bom` field should show
`none` vs `UTF-8`, and `encoding` should show `UTF-8` vs `UTF-8 with BOM`.

---

## 9. `09-empty-and-edge-cases/`

- **`empty-a.txt` / `empty-b.txt`** — both zero bytes. Should report identical
  cleanly, no crash on a completely empty diff.
- **`empty-vs-content-a.txt` (empty) / `-b.txt` (3 lines)** — the entire
  non-empty file should render as one continuous gap on the empty side, not
  three separate gaps.
- **`no-trailing-newline.txt` / `with-trailing-newline.txt`** — identical text,
  one file's last line has no trailing newline. Content should compare as
  identical; with metadata on, the `final_newline` field should show the
  difference.
- **`single-line-a.txt` / `-b.txt`** — the smallest possible real diff, useful
  as a quick sanity check when something else seems broken.

---

## 10. `10-folder-comparison/`

**`FolderA` vs `FolderB`** — the main folder-compare fixture:
- `docs/readme.txt` — identical.
- `docs/notes.txt` — differs.
- `src/main.py` — identical.
- `src/utils.py` — only in A. `src/extra.py` — only in B.
- Each folder also contains `.git/`, `node_modules/`, and `__pycache__/` —
  with the default `folder_exclude_patterns`, **none of these three should
  appear in the results at all**. Temporarily clear that setting to confirm
  they *do* show up when nothing excludes them.
- `build.log` is identical in both — a control file, useful for confirming
  identical files can be hidden/shown via **Show Identical Files**.

**`FolderA` + `FolderB` + `FolderC`** together — three-way folder compare.
`FolderC` only has `docs/readme.txt` and `src/main.py`, both matching A and
B, so it should show as missing the rest rather than as differing from them.

**`FolderD-Identical-1` / `FolderD-Identical-2`** — every file matches. This
should behave like the two-file identical case: a dialog saying so, **no
results tab opened**.

**`HashVsQuick/FolderE` vs `FolderF`** — built specifically to expose the
trade-offs of `folder_compare_mode`:

| File | Real content | `content` | `size_and_time` | `size` |
|---|---|---|---|---|
| `same-content-diff-mtime.txt` | identical | identical ✓ | **different** (wrong) | identical |
| `same-size-diff-content.txt` | different, same byte count | different ✓ | identical (wrong) | **identical** (wrong) |

Run this same pair under all three `folder_compare_mode` values and watch the
`[=]` / `[!]` markers flip on these two files. This demonstrates precisely
why `size` and `size_and_time` are heuristics, not guarantees, and that
pressing Enter on a heuristically-wrong `[!]` row and getting the real diff
is always the way to double-check a suspicious result.

---

## 11. `11-metadata-comparison/`

Turn on **Compare File Metadata** for both of these.

**`permissions-differ/file-a.txt` / `file-b.txt`** — identical content. Zip
files don't reliably carry Unix permission bits through extraction on every
platform (Windows extractors in particular usually ignore them), so this one
needs a step from you first:

- **macOS/Linux:** `chmod 444 file-b.txt` in Terminal.
- **Windows:** right-click `file-b.txt` → Properties → check **Read-only**.

Then compare the two. It should offer a metadata report instead of a
side-by-side view, and the report should mark `permissions` (and, on a
non-admin/non-root account, `readonly`) as differing.

**`content-identical-eol-differs/windows.txt` / `unix.txt`** — identical text,
different line endings, *with* `ignore_line_endings` also on. The metadata
report should mark `line_endings` with `~` (differs, but currently ignored
by your settings) rather than `!`, distinguishing "this is different" from
"this is different but you've told SubMerge not to care."

---

## Summary of verified findings from building this set

1. **`ignore_line_endings` off is the #1 source of "everything looks
   different"** on an otherwise-fine file pair. Worth checking first whenever
   a comparison looks unexpectedly noisy.
2. **`highlight_changed_line: auto` never shows the full-line yellow color
   for a matched line** when `intraline_mode` is `word` or `char` (the
   default) — only `always`, or turning `intraline_mode` off, produces it.
   `auto` and `never` are visually indistinguishable for matched lines.
3. **`folder_compare_mode: size_and_time` and `size` are real heuristics**,
   not approximations of `content` — they can both give a wrong answer in
   either direction (false different, false identical) depending on exactly
   what changed. `content` is the only mode that's always correct; the
   others trade correctness for speed on large trees.
4. **`folder_exclude_patterns` matters more than it might seem** — without
   it, `.git`, `node_modules`, and `__pycache__` directories flood folder
   comparison results with noise that has nothing to do with the actual
   project.
