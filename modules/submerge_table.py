"""
SubMerge - CSV / TSV table rendering.

Sublime cannot display a real grid inside a text buffer, so "table view" means:
parse the delimited file, then render it into a monospaced, column-aligned
plain-text table (with per-column word wrapping) in a read-only scratch buffer.
Column widths are computed across *all* panes at once so the tables line up
with each other as well as with themselves.
"""

import csv
import io
import os
import textwrap

# See submerge_session.VERSION for why this exists.
VERSION = 2

DELIMITERS = {
    ".csv": ",",
    ".tsv": "\t",
    ".tab": "\t",
    ".psv": "|",
}

VERTICAL = "\u2502"
HORIZONTAL = "\u2500"
CROSS = "\u253c"


def is_table_file(path, extra_extensions=None):
    if not path:
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext in DELIMITERS:
        return True
    return ext in [e.lower() for e in (extra_extensions or [])]


def sniff_delimiter(text, path=None, configured="auto"):
    if configured and configured != "auto":
        candidate = "\t" if configured == "\\t" else configured
        if len(candidate) == 1:
            return candidate
        # csv.reader raises TypeError - not csv.Error - for a delimiter that
        # is not exactly one character, so an unusable setting has to be
        # caught here rather than at the parse() call site.
        print("SubMerge: csv_delimiter must be a single character "
              "(got %r); falling back to auto-detection." % configured)
    if path:
        ext = os.path.splitext(path)[1].lower()
        if ext in DELIMITERS:
            return DELIMITERS[ext]
    sample = "\n".join(text.split("\n")[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except (csv.Error, TypeError):
        counts = {d: sample.count(d) for d in (",", "\t", ";", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def parse(text, delimiter):
    if len(delimiter) != 1:
        delimiter = ","
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        return [row for row in reader]
    except csv.Error:
        # Malformed quoting, an embedded NUL, an over-long field: fall back to
        # a naive split so the file is at least viewable.
        return [line.split(delimiter) for line in text.split("\n")]


def _wrap(cell, width):
    cell = cell.replace("\r", "")
    width = max(1, width)      # textwrap raises ValueError for width <= 0
    if not cell:
        return [""]
    out = []
    for paragraph in cell.split("\n"):
        if not paragraph:
            out.append("")
            continue
        out.extend(textwrap.wrap(paragraph, width=width,
                                 break_long_words=True,
                                 break_on_hyphens=False,
                                 replace_whitespace=False,
                                 drop_whitespace=False) or [""])
    return out


def compute_widths(tables, min_width=3, max_width=40, wrap=True):
    """Shared column widths across every pane's table."""
    columns = max((len(row) for table in tables for row in table), default=0)
    widths = []
    for index in range(columns):
        longest = min_width
        for table in tables:
            for row in table:
                if index < len(row):
                    longest = max(longest, len(row[index].replace("\r", "")))
        widths.append(min(longest, max_width) if wrap else longest)
    return widths


def render(table, widths, wrap=True, row_numbers=True, header_rule=True):
    """Render one parsed table.  Returns (text, record_starts).

    `record_starts[i]` is the physical line index at which record `i` begins,
    which is what lets a diff on the rendered text be mapped back to records.
    """
    number_width = len(str(max(1, len(table)))) if row_numbers else 0
    lines = []
    record_starts = []

    def emit_rule():
        parts = [HORIZONTAL * (width + 2) for width in widths]
        prefix = HORIZONTAL * (number_width + 1) + CROSS if row_numbers else ""
        lines.append(prefix + CROSS.join(parts).rstrip())

    for index, row in enumerate(table):
        record_starts.append(len(lines))
        cells = [row[i] if i < len(row) else "" for i in range(len(widths))]
        if wrap:
            wrapped = [_wrap(cell, widths[i]) for i, cell in enumerate(cells)]
        else:
            wrapped = [[cell.replace("\r", "")] for cell in cells]
        height = max(len(part) for part in wrapped) if wrapped else 1

        for physical in range(height):
            if row_numbers:
                label = str(index + 1) if physical == 0 else ""
                prefix = label.rjust(number_width) + " " + VERTICAL
            else:
                prefix = ""
            parts = []
            for column, part in enumerate(wrapped):
                text = part[physical] if physical < len(part) else ""
                parts.append(" " + text.ljust(widths[column]) + " ")
            lines.append((prefix + VERTICAL.join(parts)).rstrip())

        if header_rule and index == 0 and len(table) > 1:
            emit_rule()

    record_starts.append(len(lines))
    return "\n".join(lines), record_starts


def render_all(texts, paths, options):
    """Render several delimited files with shared column widths.

    Returns (list_of_rendered_text, delimiter).  Per-file record offsets are
    available from render() itself for callers that need to map a rendered
    line back to a record; nothing needs them at this level.
    """
    configured = options.get("delimiter", "auto")
    delimiter = sniff_delimiter(texts[0], paths[0] if paths else None, configured)
    tables = [parse(text, delimiter) for text in texts]
    # Clamp rather than trust: a negative width from the settings file reaches
    # textwrap.wrap() as an invalid width and aborts the whole comparison.
    min_width = max(1, int(options.get("min_column_width", 3) or 3))
    max_width = max(min_width, int(options.get("max_column_width", 40) or 40))
    widths = compute_widths(
        tables,
        min_width=min_width,
        max_width=max_width,
        wrap=bool(options.get("wrap_columns", True)),
    )
    rendered = []
    for table in tables:
        text, _record_starts = render(
            table, widths,
            wrap=bool(options.get("wrap_columns", True)),
            row_numbers=bool(options.get("row_numbers", True)),
            header_rule=bool(options.get("header_rule", True)),
        )
        rendered.append(text)
    return rendered, delimiter
