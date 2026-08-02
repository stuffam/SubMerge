"""
SubMerge - file metadata collection and comparison.

Used for the "compare metadata as well as content" option, for the metadata
difference report tab, and for the metadata column of the folder comparison.
"""

import hashlib
import os
import stat as stat_module
import time

# See submerge_session.VERSION for why this exists.
VERSION = 1

# Fields are reported in this order.  (key, caption)
FIELDS = [
    ("name", "File name"),
    ("path", "Full path"),
    ("size", "Size (bytes)"),
    ("modified", "Modified"),
    ("created", "Created"),
    ("accessed", "Accessed"),
    ("permissions", "Permissions"),
    ("readonly", "Read only"),
    ("lines", "Line count"),
    ("line_endings", "Line endings"),
    ("final_newline", "Ends with newline"),
    ("bom", "Byte order mark"),
    ("encoding", "Encoding (detected)"),
    ("sha1", "SHA1 (raw bytes)"),
    ("sha1_normalized", "SHA1 (EOL normalized)"),
]

# Fields that are compared when deciding "metadata is identical".
COMPARABLE = ("size", "modified", "permissions", "readonly", "lines",
              "line_endings", "final_newline", "bom", "encoding", "sha1")

# Fields that never count as a difference (they are always different).
NEVER_COMPARED = ("name", "path", "accessed", "created")

MAX_READ = 32 * 1024 * 1024     # do not slurp enormous files for hashing


def _timestamp(value):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    except (ValueError, OSError):
        return "?"


def detect_line_endings(data):
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    kinds = []
    if crlf:
        kinds.append("CRLF")
    if lf:
        kinds.append("LF")
    if cr:
        kinds.append("CR")
    if not kinds:
        return "none"
    if len(kinds) > 1:
        return "mixed (%s)" % ", ".join(kinds)
    return kinds[0]


def detect_encoding(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 with BOM"
    if data.startswith(b"\xff\xfe\x00\x00"):
        return "UTF-32 LE"
    if data.startswith(b"\x00\x00\xfe\xff"):
        return "UTF-32 BE"
    if data.startswith(b"\xff\xfe"):
        return "UTF-16 LE"
    if data.startswith(b"\xfe\xff"):
        return "UTF-16 BE"
    try:
        data.decode("utf-8")
        return "UTF-8" if any(b > 127 for b in data[:4096]) else "ASCII"
    except UnicodeDecodeError:
        return "binary / 8-bit"


def detect_bom(data):
    for marker, name in ((b"\xef\xbb\xbf", "UTF-8"),
                         (b"\xff\xfe\x00\x00", "UTF-32 LE"),
                         (b"\x00\x00\xfe\xff", "UTF-32 BE"),
                         (b"\xff\xfe", "UTF-16 LE"),
                         (b"\xfe\xff", "UTF-16 BE")):
        if data.startswith(marker):
            return name
    return "none"


def normalize_eol(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def collect(path):
    """Return a metadata dict for `path` (never raises)."""
    info = {"name": os.path.basename(path), "path": path}
    try:
        st = os.stat(path)
    except OSError as exc:
        info["error"] = str(exc)
        return info

    info["size"] = st.st_size
    info["modified"] = _timestamp(st.st_mtime)
    info["created"] = _timestamp(getattr(st, "st_birthtime", st.st_ctime))
    info["accessed"] = _timestamp(st.st_atime)
    info["permissions"] = oct(stat_module.S_IMODE(st.st_mode))[2:].rjust(3, "0")
    info["readonly"] = not os.access(path, os.W_OK)
    info["_mtime"] = int(st.st_mtime)

    if st.st_size > MAX_READ:
        for key in ("lines", "line_endings", "final_newline", "bom",
                    "encoding", "sha1", "sha1_normalized"):
            info[key] = "(file too large)"
        return info

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        info["error"] = str(exc)
        return info

    normalized = normalize_eol(data)
    info["lines"] = normalized.count(b"\n") + (
        0 if (not normalized or normalized.endswith(b"\n")) else 1)
    info["line_endings"] = detect_line_endings(data)
    info["final_newline"] = bool(data) and data.endswith((b"\n", b"\r"))
    info["bom"] = detect_bom(data)
    info["encoding"] = detect_encoding(data)
    info["sha1"] = hashlib.sha1(data).hexdigest()
    info["sha1_normalized"] = hashlib.sha1(normalized).hexdigest()
    return info


def differing_fields(metas, fields=COMPARABLE):
    """Return the list of field keys whose value is not the same everywhere."""
    out = []
    for key in fields:
        values = [meta.get(key) for meta in metas]
        if any(value != values[0] for value in values[1:]):
            out.append(key)
    return out


def same_metadata(metas, fields=COMPARABLE):
    return not differing_fields(metas, fields)


def short_summary(keys):
    """'size, modified' - used in the folder comparison rows."""
    captions = dict(FIELDS)
    return ", ".join(captions.get(k, k).lower() for k in keys)


def _format(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "-"
    return str(value)


def render_report(paths, metas, content_identical, compare_fields=COMPARABLE):
    """Build the text of the metadata difference tab."""
    letters = "ABC"
    width = max([len(_format(m.get(k))) for m in metas for k, _ in FIELDS] + [12])
    width = min(width, 60)
    caption_width = max(len(c) for _, c in FIELDS) + 2

    lines = []
    lines.append("SubMerge  \u2014  File Metadata Comparison")
    lines.append("")
    for index, path in enumerate(paths):
        lines.append("  %s: %s" % (letters[index], path))
    lines.append("")
    if content_identical:
        lines.append("  Content: IDENTICAL")
    else:
        lines.append("  Content: DIFFERENT")
    differing = differing_fields(metas, compare_fields)
    if differing:
        lines.append("  Metadata: DIFFERENT (%s)" % short_summary(differing))
    else:
        lines.append("  Metadata: IDENTICAL")
    lines.append("")

    header = "    " + "".ljust(caption_width)
    for index in range(len(metas)):
        header += letters[index].ljust(width + 2)
    lines.append(header.rstrip())
    lines.append("    " + "-" * (caption_width + (width + 2) * len(metas)))

    for key, caption in FIELDS:
        values = [_format(meta.get(key)) for meta in metas]
        same = all(v == values[0] for v in values[1:])
        if key in NEVER_COMPARED:
            marker = "    "
        elif same:
            marker = "  = "
        elif key not in compare_fields:
            # Differs, but excluded from the comparison (e.g. line endings
            # while "ignore_line_endings" is on).
            marker = "  ~ "
        else:
            marker = "  ! "
        row = marker + caption.ljust(caption_width)
        for value in values:
            if len(value) > width:
                value = value[:width - 1] + "\u2026"
            row += value.ljust(width + 2)
        lines.append(row.rstrip())

    lines.append("")
    lines.append("  '!' marks a field that differs, '=' a field that matches,")
    lines.append("  '~' a field that differs but is currently ignored by your "
                 "settings.")
    lines.append("  Name, path, created and accessed times are shown for "
                 "reference only and never")
    lines.append("  count as a difference.")
    return "\n".join(lines)
