"""
SubMerge - core diff engine.

Pure Python 3.8, no Sublime API imports, so it can be unit tested outside of
Sublime Text.

The engine aligns 2 or 3 sequences of lines into a single table of "alignment
rows".  Every row holds one entry per pane; the entry is either the index of a
line in that pane, or None, which means "this pane has nothing here" (a gap).

    rows = [
        (0,    0,    0   ),   # all three panes share this line
        (1,    1,    None),   # pane C is missing a line here  -> gap in C
        (2,    None, 1   ),   # pane B is missing a line here  -> gap in B
        (None, 2,    None),   # pane B has an extra line       -> gap in A and C
    ]
"""

import difflib
import re
from collections import deque

# Bumped whenever the public API of this module changes.  SubMerge.py checks
# it at load time to catch the "Sublime is still running the old sub-module"
# situation that happens when the package is overwritten in place.
VERSION = 3

EQUAL = "equal"
CHANGED = "changed"

# Panes are labelled A/B/C everywhere they are shown to the user - in status
# messages, folder-comparison presence columns and metadata report headers.
# The label set is what caps the number of panes, so the two live together:
# supporting a fourth pane means adding a letter here and nothing else.
PANE_LETTERS = "ABC"
MAX_PANES = len(PANE_LETTERS)

_WORD_RE = re.compile(r"\w+|[ \t]+|[^\w \t]")


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

class CompareOptions(object):
    """Everything that influences how two lines are considered 'equal'."""

    def __init__(self,
                 ignore_whitespace=False,
                 ignore_all_whitespace=False,
                 ignore_case=False,
                 ignore_blank_lines=False,
                 ignore_line_endings=True,
                 intraline_mode="word",
                 detect_moved=True,
                 moved_min_length=3):
        self.ignore_whitespace = ignore_whitespace
        self.ignore_all_whitespace = ignore_all_whitespace
        self.ignore_case = ignore_case
        self.ignore_blank_lines = ignore_blank_lines
        self.ignore_line_endings = ignore_line_endings
        self.intraline_mode = intraline_mode  # "word" | "char" | "none"
        self.detect_moved = detect_moved
        self.moved_min_length = moved_min_length

    def key(self, line):
        s = line
        if self.ignore_line_endings:
            s = s.rstrip("\r\n")
        if self.ignore_all_whitespace:
            s = re.sub(r"\s+", "", s)
        elif self.ignore_whitespace:
            s = re.sub(r"[ \t]+", " ", s.strip())
        if self.ignore_case:
            s = s.lower()
        return s

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        opts = cls()
        for k, v in (d or {}).items():
            if hasattr(opts, k):
                setattr(opts, k, v)
        return opts


# ---------------------------------------------------------------------------
# pairwise alignment
# ---------------------------------------------------------------------------

def _pairwise(base_keys, other_keys):
    """Return an ordered list of (base_index|None, other_index|None) pairs."""
    matcher = difflib.SequenceMatcher(None, base_keys, other_keys, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((i1 + k, j1 + k))
        elif tag == "replace":
            # Pair the changed lines up 1:1 so that intra-line highlighting has
            # a sensible partner; pad the shorter side with gaps.
            for k in range(max(i2 - i1, j2 - j1)):
                a = i1 + k if i1 + k < i2 else None
                b = j1 + k if j1 + k < j2 else None
                pairs.append((a, b))
        elif tag == "delete":
            for k in range(i1, i2):
                pairs.append((k, None))
        else:  # insert
            for k in range(j1, j2):
                pairs.append((None, k))
    return pairs


def _index_pairs(pairs, base_len):
    """Split pairs into {base_index: other_index} and {base_index: [inserts]}."""
    matched = {}
    inserts = {}
    pending = []
    for a, b in pairs:
        if a is None:
            if b is not None:
                pending.append(b)
        else:
            if pending:
                inserts[a] = pending
                pending = []
            matched[a] = b
    if pending:
        inserts[base_len] = pending
    return matched, inserts


# ---------------------------------------------------------------------------
# alignment result
# ---------------------------------------------------------------------------

class Hunk(object):
    """A contiguous run of non-equal alignment rows."""

    __slots__ = ("start_row", "end_row", "index")

    def __init__(self, start_row, end_row, index):
        self.start_row = start_row      # inclusive
        self.end_row = end_row          # exclusive
        self.index = index

    def __repr__(self):
        return "<Hunk #%d rows %d..%d>" % (self.index, self.start_row, self.end_row)


class Alignment(object):
    def __init__(self, pane_lines, options):
        self.options = options
        self.pane_count = len(pane_lines)
        self.pane_lines = pane_lines
        self.rows = []                       # list[tuple[Optional[int], ...]]
        self.row_kind = []                   # EQUAL | CHANGED
        self.line_to_row = [dict() for _ in pane_lines]
        self.gaps = [dict() for _ in pane_lines]   # line_index -> gap size (rows)
        self.inline = [dict() for _ in pane_lines]  # line_index -> [(start, end)]
        self.moved = [dict() for _ in pane_lines]  # line_index -> (pane, line)
        self.hunks = []
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self):
        opts = self.options
        keys = [[opts.key(line) for line in lines]
                for lines in self.pane_lines]
        base_keys = keys[0]
        base_len = len(base_keys)

        matched = [None]
        inserts = [None]
        for p in range(1, self.pane_count):
            m, i = _index_pairs(_pairwise(base_keys, keys[p]), base_len)
            matched.append(m)
            inserts.append(i)

        rows = []
        for a in range(base_len + 1):
            ins = [inserts[p].get(a, []) for p in range(1, self.pane_count)]
            for k in range(max([len(x) for x in ins]) if ins else 0):
                row = [None] * self.pane_count
                for p in range(1, self.pane_count):
                    lst = ins[p - 1]
                    if k < len(lst):
                        row[p] = lst[k]
                rows.append(tuple(row))
            if a < base_len:
                row = [a] + [matched[p].get(a) for p in range(1, self.pane_count)]
                rows.append(tuple(row))
        self.rows = rows

        self._classify(keys)
        self._compute_gaps()
        self._compute_hunks()
        if self.options.intraline_mode != "none":
            self._compute_intraline()
        if self.options.detect_moved:
            self._detect_moved(keys)

    def _classify(self, keys):
        blank_ok = self.options.ignore_blank_lines
        for row in self.rows:
            present = [(p, i) for p, i in enumerate(row) if i is not None]
            if len(present) == self.pane_count:
                first = keys[present[0][0]][present[0][1]]
                same = all(keys[p][i] == first for p, i in present[1:])
                self.row_kind.append(EQUAL if same else CHANGED)
            else:
                if blank_ok and all(not keys[p][i].strip() for p, i in present):
                    self.row_kind.append(EQUAL)
                else:
                    self.row_kind.append(CHANGED)
        for r, row in enumerate(self.rows):
            for p, i in enumerate(row):
                if i is not None:
                    self.line_to_row[p][i] = r

    def _compute_gaps(self):
        pending = [0] * self.pane_count
        for row in self.rows:
            for p, i in enumerate(row):
                if i is None:
                    pending[p] += 1
                elif pending[p]:
                    self.gaps[p][i] = pending[p]
                    pending[p] = 0
        for p in range(self.pane_count):
            if pending[p]:
                self.gaps[p][len(self.pane_lines[p])] = pending[p]

    def _compute_hunks(self):
        start = None
        for r, kind in enumerate(self.row_kind):
            if kind == CHANGED and start is None:
                start = r
            elif kind == EQUAL and start is not None:
                self.hunks.append(Hunk(start, r, len(self.hunks)))
                start = None
        if start is not None:
            self.hunks.append(Hunk(start, len(self.row_kind), len(self.hunks)))

    def _compute_intraline(self):
        mode = self.options.intraline_mode
        ic = self.options.ignore_case
        for r, row in enumerate(self.rows):
            if self.row_kind[r] != CHANGED:
                continue
            if row[0] is None:
                continue
            base_text = self.pane_lines[0][row[0]]
            base_ranges = []
            for p in range(1, self.pane_count):
                if row[p] is None:
                    continue
                other_text = self.pane_lines[p][row[p]]
                if base_text == other_text:
                    continue
                a_r, b_r = intraline_ranges(base_text, other_text, mode, ic)
                base_ranges.extend(a_r)
                if b_r:
                    self.inline[p][row[p]] = b_r
            if base_ranges:
                self.inline[0][row[0]] = merge_ranges(base_ranges)

    def _detect_moved(self, keys):
        """Pair up lines that exist only in one pane with an identical line
        that exists only in another pane: those are moved, not added/removed."""
        min_length = max(1, int(self.options.moved_min_length or 1))

        unmatched = [[] for _ in range(self.pane_count)]
        for row in self.rows:
            for pane, line in enumerate(row):
                if line is None:
                    continue
                if any(row[other] is None
                       for other in range(self.pane_count) if other != pane):
                    unmatched[pane].append(line)

        for left in range(self.pane_count):
            for right in range(left + 1, self.pane_count):
                buckets = {}
                for line in unmatched[right]:
                    if line in self.moved[right]:
                        continue
                    key = keys[right][line].strip()
                    if len(key) < min_length:
                        continue
                    buckets.setdefault(key, deque()).append(line)

                for line in unmatched[left]:
                    if line in self.moved[left]:
                        continue
                    key = keys[left][line].strip()
                    if len(key) < min_length:
                        continue
                    candidates = buckets.get(key)
                    if not candidates:
                        continue
                    # Consume candidates rather than re-scanning past the ones
                    # already paired: a line can only be moved once, so a used
                    # candidate is never a match again, and rescanning makes
                    # this quadratic in the number of identical unmatched
                    # lines sharing a key.
                    partner = None
                    while candidates:
                        candidate = candidates.popleft()
                        if candidate not in self.moved[right]:
                            partner = candidate
                            break
                    if partner is None:
                        continue
                    self.moved[left][line] = (right, partner)
                    self.moved[right][partner] = (left, line)

    # -- queries ------------------------------------------------------------

    def row_of_line(self, pane, line):
        return self.line_to_row[pane].get(line)

    def hunk_at_row(self, row):
        for h in self.hunks:
            if h.start_row <= row < h.end_row:
                return h
        return None

    def hunk_for_line(self, pane, line):
        row = self.row_of_line(pane, line)
        if row is None:
            return None
        return self.hunk_at_row(row)

    def lines_in_hunk(self, hunk, pane):
        out = [self.rows[r][pane] for r in range(hunk.start_row, hunk.end_row)]
        return [i for i in out if i is not None]

    def next_present_line(self, pane, row):
        """First line index in `pane` at or after alignment row `row`."""
        for r in range(row, len(self.rows)):
            i = self.rows[r][pane]
            if i is not None:
                return i
        return len(self.pane_lines[pane])

    def prev_present_line(self, pane, row):
        for r in range(row, -1, -1):
            i = self.rows[r][pane]
            if i is not None:
                return i
        return None

    def hunk_is_moved_only(self, hunk):
        """True when every differing line in the hunk was matched elsewhere."""
        found = False
        for row in range(hunk.start_row, hunk.end_row):
            for pane, line in enumerate(self.rows[row]):
                if line is None:
                    continue
                if line not in self.moved[pane]:
                    return False
                found = True
        return found

    def stats(self):
        changed = sum(1 for k in self.row_kind if k == CHANGED)
        return {
            "rows": len(self.rows),
            "changed_rows": changed,
            "hunks": len(self.hunks),
            "moved": sum(len(m) for m in self.moved) // 2,
            "identical": changed == 0,
        }

    @property
    def identical(self):
        return all(kind == EQUAL for kind in self.row_kind)


# ---------------------------------------------------------------------------
# intra-line diffing
# ---------------------------------------------------------------------------

def _tokenize(text, mode):
    if mode == "char":
        toks = list(text)
    else:
        toks = _WORD_RE.findall(text)
    spans = []
    pos = 0
    for t in toks:
        spans.append((pos, pos + len(t)))
        pos += len(t)
    return toks, spans


def intraline_ranges(a_text, b_text, mode="word", ignore_case=False):
    """Return (a_ranges, b_ranges) of differing character spans."""
    a_toks, a_spans = _tokenize(a_text, mode)
    b_toks, b_spans = _tokenize(b_text, mode)
    a_cmp = [t.lower() for t in a_toks] if ignore_case else a_toks
    b_cmp = [t.lower() for t in b_toks] if ignore_case else b_toks

    matcher = difflib.SequenceMatcher(None, a_cmp, b_cmp, autojunk=False)
    a_out, b_out = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            a_out.append((a_spans[i1][0], a_spans[i2 - 1][1]))
        elif tag == "insert":
            # Zero width on this side; mark the seam so the user can see it.
            pos = a_spans[i1][0] if i1 < len(a_spans) else len(a_text)
            a_out.append((max(0, pos - 1), pos))
        if j2 > j1:
            b_out.append((b_spans[j1][0], b_spans[j2 - 1][1]))
        elif tag == "delete":
            pos = b_spans[j1][0] if j1 < len(b_spans) else len(b_text)
            b_out.append((max(0, pos - 1), pos))
    return merge_ranges(a_out), merge_ranges(b_out)


def merge_ranges(ranges):
    if not ranges:
        return []
    ranges = sorted(ranges)
    out = [list(ranges[0])]
    for s, e in ranges[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def split_lines(text):
    """Split into lines without keeping the line terminators."""
    return text.split("\n")


def compare_texts(texts, options):
    return Alignment([split_lines(t) for t in texts], options)
