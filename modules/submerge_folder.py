"""
SubMerge - folder comparison.

Builds a recursive tree of two or three folders and renders it into a read-only
scratch view.  Row metadata (which real paths a line maps to) is kept in a
module level registry keyed by view id, so pressing Enter on a row can open the
matching file comparison.
"""

import fnmatch
import hashlib
import os

import sublime

from . import submerge_metadata as metadata
from .submerge_session import PACKAGE, setting, title_for, bump_color_scheme

# See submerge_session.VERSION for why this exists.
VERSION = 2

# view_id -> {"roots": [...], "rows": {row: entry}, "options": {...}}
_folder_views = {}

STATUS_IDENTICAL = "identical"
STATUS_METADATA = "metadata"
STATUS_DIFFERENT = "different"
STATUS_UNIQUE = "unique"

MARK = {
    STATUS_IDENTICAL: "[=]",
    STATUS_METADATA: "[~]",
    STATUS_DIFFERENT: "[!]",
    STATUS_UNIQUE: "[+]",
}

RANK = {
    STATUS_IDENTICAL: 0,
    STATUS_METADATA: 1,
    STATUS_DIFFERENT: 2,
    STATUS_UNIQUE: 3,
}


class Node(object):
    def __init__(self, name, is_dir, present, paths):
        self.name = name
        self.is_dir = is_dir
        self.present = present      # list[bool] per root
        self.paths = paths          # list[str|None] per root
        self.children = []
        self.status = STATUS_IDENTICAL
        self.meta_diff = []         # differing metadata field names

    @property
    def unique(self):
        return not all(self.present)


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------

def _excluded(name, patterns):
    for pattern in patterns or []:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _content_signature(path, mode, ignore_eol, chunk=1 << 16):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    if mode == "size":
        return ("size", stat.st_size)
    if mode == "size_and_time":
        return ("st", stat.st_size, int(stat.st_mtime))

    digest = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            if ignore_eol:
                # Normalize CRLF/CR to LF before hashing so that Windows and
                # Unix copies of the same text hash identically.
                tail = b""
                while True:
                    block = handle.read(chunk)
                    if not block:
                        break
                    block = tail + block
                    tail = block[-1:] if block.endswith(b"\r") else b""
                    if tail:
                        block = block[:-1]
                    digest.update(metadata.normalize_eol(block))
                if tail:
                    digest.update(metadata.normalize_eol(tail))
            else:
                while True:
                    block = handle.read(chunk)
                    if not block:
                        break
                    digest.update(block)
    except OSError:
        return None
    return ("md5", digest.hexdigest())


def _compare_files(paths, options):
    """Return (content_identical, differing_metadata_fields)."""
    present = [p for p in paths if p]
    if len(present) < 2:
        return False, []

    signatures = [_content_signature(p, options["compare_mode"],
                                     options["ignore_line_endings"])
                  for p in present]
    same = (not any(s is None for s in signatures)
            and all(s == signatures[0] for s in signatures[1:]))

    diff_fields = []
    if options.get("compare_metadata"):
        metas = [metadata.collect(p) for p in present]
        fields = options.get("metadata_fields") or metadata.COMPARABLE
        if options["ignore_line_endings"]:
            fields = [f for f in fields
                      if f not in ("line_endings", "sha1", "size")]
        diff_fields = metadata.differing_fields(metas, fields)
    return same, diff_fields


def scan(roots, options):
    """Return (root Node, summary dict)."""
    exclude = options.get("exclude", [])
    max_depth = int(options.get("max_depth", 0) or 0)
    summary = {"files": 0, "dirs": 0, "different": 0, "metadata": 0,
               "unique": 0, "identical": 0}

    def walk(rel, depth):
        paths = [os.path.join(root, rel) if rel else root for root in roots]
        exists = [os.path.isdir(p) for p in paths]
        names = set()
        for path, ok in zip(paths, exists):
            if not ok:
                continue
            try:
                for name in os.listdir(path):
                    if not _excluded(name, exclude):
                        names.add(name)
            except OSError:
                pass

        children = []
        for name in sorted(names, key=lambda s: s.lower()):
            child_paths = []
            child_present = []
            child_is_dir = False
            for path, ok in zip(paths, exists):
                candidate = os.path.join(path, name) if ok else None
                if candidate and os.path.exists(candidate):
                    child_paths.append(candidate)
                    child_present.append(True)
                    if os.path.isdir(candidate):
                        child_is_dir = True
                else:
                    child_paths.append(None)
                    child_present.append(False)

            node = Node(name, child_is_dir, child_present, child_paths)
            if child_is_dir:
                summary["dirs"] += 1
                if max_depth and depth + 1 > max_depth:
                    node.status = (STATUS_UNIQUE if node.unique
                                   else STATUS_IDENTICAL)
                else:
                    node.children = walk(
                        os.path.join(rel, name) if rel else name, depth + 1)
                    if node.unique:
                        node.status = STATUS_UNIQUE
                    else:
                        worst = max([RANK[c.status] for c in node.children],
                                    default=0)
                        node.status = {0: STATUS_IDENTICAL,
                                       1: STATUS_METADATA,
                                       2: STATUS_DIFFERENT,
                                       3: STATUS_DIFFERENT}[worst]
            else:
                summary["files"] += 1
                if node.unique:
                    node.status = STATUS_UNIQUE
                    summary["unique"] += 1
                else:
                    same, diff_fields = _compare_files(child_paths, options)
                    node.meta_diff = diff_fields
                    if not same:
                        node.status = STATUS_DIFFERENT
                        summary["different"] += 1
                    elif diff_fields:
                        node.status = STATUS_METADATA
                        summary["metadata"] += 1
                    else:
                        node.status = STATUS_IDENTICAL
                        summary["identical"] += 1
            children.append(node)
        return children

    children = walk("", 0)
    root = Node(os.path.basename(roots[0].rstrip(os.sep)) or roots[0],
                True, [True] * len(roots), list(roots))
    root.children = children
    return root, summary


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _presence_column(node, count):
    letters = "ABC"
    return "".join(letters[i] if node.present[i] else "-" for i in range(count))


def _keep(node, show_identical):
    """Should this node appear in the results?"""
    if show_identical:
        return True
    if node.status != STATUS_IDENTICAL:
        return True
    # A folder is kept if anything below it is kept.
    return any(_keep(child, show_identical) for child in node.children)


def render(root, roots, options, summary):
    count = len(roots)
    show_identical = bool(options.get("show_identical", True))
    with_metadata = bool(options.get("compare_metadata"))
    lines = []
    meta = {}

    lines.append("SubMerge  \u2014  Folder Comparison")
    for index, path in enumerate(roots):
        lines.append("  %s: %s" % ("ABC"[index], path))
    lines.append("")
    legend = "  [=] identical    [!] content differs    [+] only in some folders"
    if with_metadata:
        legend += "    [~] content identical, metadata differs"
    lines.append(legend)
    lines.append("  Press Enter (or double-click) on a row to compare / open it."
                 "   F5 rescans.")
    if not show_identical:
        lines.append("  Identical files are hidden "
                     "(Tools > SubMerge > Comparison Options).")
    lines.append("")

    def emit(node, depth):
        if not _keep(node, show_identical):
            return
        indent = "  " * (depth + 1)
        name = node.name + ("/" if node.is_dir else "")
        text = "%s%s %s  %s" % (indent, MARK[node.status],
                                _presence_column(node, count), name)
        if node.meta_diff and node.status == STATUS_METADATA:
            text += "   \u2190 " + metadata.short_summary(node.meta_diff)
        elif node.meta_diff:
            text += "   (+ " + metadata.short_summary(node.meta_diff) + ")"
        meta[len(lines)] = node
        lines.append(text)
        for child in node.children:
            emit(child, depth + 1)

    for child in root.children:
        emit(child, 0)

    lines.append("")
    tally = ("  %d folder(s), %d file(s): %d different, %d unique, %d identical"
             % (summary["dirs"], summary["files"], summary["different"],
                summary["unique"], summary["identical"]))
    if with_metadata:
        tally += ", %d metadata-only" % summary["metadata"]
    lines.append(tally)
    return "\n".join(lines), meta


def folder_options():
    return {
        "exclude": setting("folder_exclude_patterns",
                           [".git", ".svn", ".hg", "node_modules", "__pycache__",
                            "*.pyc", ".DS_Store"]),
        "max_depth": setting("folder_max_depth", 0),
        "compare_mode": setting("folder_compare_mode", "content"),
        "show_identical": setting("folder_show_identical", True),
        "compare_metadata": setting("compare_metadata", False),
        "metadata_fields": setting("metadata_fields", None),
        "ignore_line_endings": setting("ignore_line_endings", True),
    }


def open_folder_compare(window, roots, window_factory=None):
    """Scan (usually off the main thread) then show the result.

    `window_factory` is called on the main thread only when a result tab is
    actually going to be created, so the "open in a new window" option does
    not leave an empty window behind when the folders turn out to match.
    """
    options = folder_options()
    sublime.status_message("SubMerge: scanning folders\u2026")
    root, summary = scan(roots, options)

    everything_matches = (summary["different"] == 0 and summary["unique"] == 0
                          and summary["metadata"] == 0)
    if everything_matches and summary["files"]:
        sublime.set_timeout(lambda: _identical_dialog(roots, summary), 0)
        return

    text, meta = render(root, roots, options, summary)

    def show():
        target = window_factory(window) if window_factory else window
        _present(target or window, roots, text, meta, options)

    sublime.set_timeout(show, 0)


def _identical_dialog(roots, summary):
    detail = "All %d file(s) are identical" % summary["files"]
    if setting("compare_metadata", False):
        detail += " in content and metadata"
    sublime.message_dialog(
        "SubMerge\n\n%s.\n\n%s\n\nNo comparison tab was opened."
        % (detail, "\n".join(roots)))
    sublime.status_message("SubMerge: folders are identical")


def _present(window, roots, text, meta, options):
    view = window.new_file()
    bump_color_scheme(view)
    view.set_name(title_for("", [
        os.path.basename(r.rstrip(os.sep)) or r for r in roots]))
    view.set_scratch(True)
    view.settings().set("submerge_folder_view", True)
    view.settings().set("word_wrap", False)
    view.settings().set("draw_indent_guides", False)
    view.settings().set("gutter", False)
    view.settings().set("submerge_folder_roots", list(roots))
    view.run_command("submerge_replace_all", {"text": text})
    view.set_read_only(True)
    try:
        view.assign_syntax(
            "Packages/%s/SubMergeFolder.sublime-syntax" % PACKAGE)
    except Exception:
        pass
    _folder_views[view.id()] = {"roots": list(roots), "rows": meta,
                                "options": options}
    return view


def entry_for_row(view, row):
    data = _folder_views.get(view.id())
    if not data:
        return None
    return data["rows"].get(row)


def roots_for_view(view):
    data = _folder_views.get(view.id())
    return data["roots"] if data else []


def forget(view_id):
    _folder_views.pop(view_id, None)


def rescan(view):
    data = _folder_views.get(view.id())
    if not data:
        return
    data["options"] = folder_options()

    def work():
        root, summary = scan(data["roots"], data["options"])
        text, meta = render(root, data["roots"], data["options"], summary)
        sublime.set_timeout(lambda: _apply_rescan(view, data, text, meta), 0)

    sublime.status_message("SubMerge: rescanning folders\u2026")
    sublime.set_timeout_async(work, 0)


def _apply_rescan(view, data, text, meta):
    if not view.is_valid():
        return
    view.set_read_only(False)
    view.run_command("submerge_replace_all", {"text": text})
    view.set_read_only(True)
    data["rows"] = meta
    sublime.status_message("SubMerge: folder comparison refreshed")
