"""
SubMerge - file metadata collection and comparison.

Used for the "compare metadata as well as content" option, for the metadata
difference report tab, and for the metadata column of the folder comparison.

No Sublime imports, so it can be tested from a plain Python interpreter.
"""

import codecs
import hashlib
import os
import stat as stat_module
import time

from .submerge_core import PANE_LETTERS

# See submerge_session.VERSION for why this exists.
VERSION = 2

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

# Fields that require reading the file rather than just stat()ing it.
DERIVED = ("lines", "line_endings", "final_newline", "bom", "encoding",
           "sha1", "sha1_normalized")

MAX_READ = 32 * 1024 * 1024     # do not hash enormous files
CHUNK = 1 << 16                 # streaming read size


def _timestamp(value):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    except (ValueError, OSError):
        return "?"


# ---------------------------------------------------------------------------
# byte-level detection
# ---------------------------------------------------------------------------

def normalize_eol(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _describe_line_endings(crlf, lf, cr):
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


def detect_line_endings(data):
    """Whole-buffer form of what _Scan counts incrementally."""
    crlf = data.count(b"\r\n")
    return _describe_line_endings(crlf, data.count(b"\n") - crlf,
                                  data.count(b"\r") - crlf)


def detect_bom(data):
    for marker, name in ((b"\xef\xbb\xbf", "UTF-8"),
                         (b"\xff\xfe\x00\x00", "UTF-32 LE"),
                         (b"\x00\x00\xfe\xff", "UTF-32 BE"),
                         (b"\xff\xfe", "UTF-16 LE"),
                         (b"\xfe\xff", "UTF-16 BE")):
        if data.startswith(marker):
            return name
    return "none"


def _describe_encoding(head, valid_utf8, high_bit):
    bom = detect_bom(head)
    if bom == "UTF-8":
        return "UTF-8 with BOM"
    if bom != "none":
        return bom
    if not valid_utf8:
        return "binary / 8-bit"
    return "UTF-8" if high_bit else "ASCII"


def detect_encoding(data):
    """Whole-buffer form of what _Scan determines incrementally."""
    try:
        data.decode("utf-8")
        valid = True
    except UnicodeDecodeError:
        valid = False
    return _describe_encoding(data[:4], valid,
                              any(b > 127 for b in data[:4096]))


# ---------------------------------------------------------------------------
# single-pass file scan
# ---------------------------------------------------------------------------

class _Scan(object):
    """Accumulates every derived metadata field in one forward pass.

    The previous implementation read the whole file into memory and then
    walked it four separate times (normalize, count, hash raw, hash
    normalized).  Folder comparison calls this once per file per root, so
    that cost is paid thousands of times in a single scan; doing it
    incrementally keeps peak memory at one chunk and lets the folder
    comparison reuse these digests instead of hashing the same bytes again.
    """

    def __init__(self):
        self.raw = hashlib.sha1()
        self.normalized = hashlib.sha1()
        self.crlf = 0
        self.lf = 0
        self.cr = 0
        self.newlines = 0        # newlines *after* EOL normalization
        self.head = b""          # first 4 bytes, for BOM detection
        self.last = b""          # final byte, for "ends with newline"
        self.size = 0
        self.high_bit = False    # any byte > 127 in the first 4 KiB
        self.valid_utf8 = True
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self._carry = b""        # a trailing CR held back across a boundary

    def feed(self, block):
        if not block:
            return
        # Everything up to the carry handling looks at the original bytes, in
        # order, exactly as they appear on disk.
        if len(self.head) < 4:
            self.head = (self.head + block)[:4]
        if not self.high_bit and self.size < 4096:
            if any(b > 127 for b in block[:4096 - self.size]):
                self.high_bit = True
        self.size += len(block)
        self.last = block[-1:]
        self.raw.update(block)
        if self.valid_utf8:
            try:
                self._utf8.decode(block)
            except UnicodeDecodeError:
                self.valid_utf8 = False

        # Hold back a trailing CR so a CRLF straddling two reads is counted as
        # one CRLF rather than as a lone CR followed by a lone LF.
        block = self._carry + block
        if block.endswith(b"\r"):
            self._carry, block = b"\r", block[:-1]
        else:
            self._carry = b""
        self._count(block)

    def _count(self, block):
        crlf = block.count(b"\r\n")
        self.crlf += crlf
        self.lf += block.count(b"\n") - crlf
        self.cr += block.count(b"\r") - crlf
        normalized = normalize_eol(block)
        self.newlines += normalized.count(b"\n")
        self.normalized.update(normalized)

    def finish(self):
        if self._carry:
            self._count(self._carry)
            self._carry = b""
        if self.valid_utf8:
            try:
                self._utf8.decode(b"", True)     # flush a truncated sequence
            except UnicodeDecodeError:
                self.valid_utf8 = False
        return self

    # -- derived fields -----------------------------------------------------

    @property
    def lines(self):
        if not self.size:
            return 0
        return self.newlines + (0 if self.last in (b"\n", b"\r") else 1)

    @property
    def line_endings(self):
        return _describe_line_endings(self.crlf, self.lf, self.cr)

    @property
    def final_newline(self):
        return bool(self.size) and self.last in (b"\n", b"\r")

    @property
    def bom(self):
        return detect_bom(self.head)

    @property
    def encoding(self):
        return _describe_encoding(self.head, self.valid_utf8, self.high_bit)

    def fields(self):
        """The derived half of a metadata dict."""
        return {
            "lines": self.lines,
            "line_endings": self.line_endings,
            "final_newline": self.final_newline,
            "bom": self.bom,
            "encoding": self.encoding,
            "sha1": self.raw.hexdigest(),
            "sha1_normalized": self.normalized.hexdigest(),
        }


def scan_file(path, chunk=CHUNK):
    """Stream `path` once and return the completed _Scan.  May raise OSError."""
    scan = _Scan()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            scan.feed(block)
    return scan.finish()


# ---------------------------------------------------------------------------
# collection and comparison
# ---------------------------------------------------------------------------

def collect(path):
    """Return a metadata dict for `path` (never raises).

    On failure the dict carries an "error" key and none of the derived
    fields; callers must treat that as "unknown", not as "empty".
    """
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

    if st.st_size > MAX_READ:
        for key in DERIVED:
            info[key] = "(file too large)"
        return info

    try:
        info.update(scan_file(path).fields())
    except OSError as exc:
        info["error"] = str(exc)
    return info


def differing_fields(metas, fields=COMPARABLE):
    """Return the list of field keys whose value is not the same everywhere.

    A file we could not read has no values to compare, so rather than let a
    row of missing values look like a match, every requested field counts as
    differing - the same direction the content signature already takes when a
    file cannot be hashed.
    """
    if any(meta.get("error") for meta in metas):
        return list(fields)
    out = []
    for key in fields:
        values = [meta.get(key) for meta in metas]
        if any(value != values[0] for value in values[1:]):
            out.append(key)
    return out


def comparable_fields(configured=None, ignore_line_endings=True):
    """The fields that count as a metadata difference, given the settings.

    With EOL differences ignored, CRLF and LF copies of the same text differ
    only in their byte count and raw hash, so reporting those three as
    metadata differences would contradict the option the user just set.
    """
    fields = list(configured or COMPARABLE)
    if ignore_line_endings:
        fields = [f for f in fields
                  if f not in ("line_endings", "sha1", "size")]
    return fields


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
    width = max([len(_format(m.get(k))) for m in metas for k, _ in FIELDS] + [12])
    width = min(width, 60)
    caption_width = max(len(c) for _, c in FIELDS) + 2

    lines = []
    lines.append("SubMerge  —  File Metadata Comparison")
    lines.append("")
    for index, path in enumerate(paths):
        lines.append("  %s: %s" % (PANE_LETTERS[index], path))
        # An unreadable file otherwise renders as a column of "-" with no
        # indication that anything went wrong.
        error = metas[index].get("error") if index < len(metas) else None
        if error:
            lines.append("       ! could not be read: %s" % error)
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
        header += PANE_LETTERS[index].ljust(width + 2)
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
                value = value[:width - 1] + "…"
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
