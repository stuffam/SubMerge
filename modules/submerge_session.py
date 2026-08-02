"""
SubMerge - session management, rendering and scroll synchronization.
"""

import json
import os

import sublime

from .submerge_core import Alignment, CompareOptions, CHANGED, split_lines

# Bumped whenever the public surface of this module changes (new functions,
# renamed constants, changed color/rule shape, ...).  SubMerge.py checks this
# at load time to catch the "Sublime is still running an old copy of this
# module" situation that happens when the package is overwritten in place
# without a full restart - see _check_modules() there for why this matters.
VERSION = 6

SETTINGS_FILE = "SubMerge.sublime-settings"
COLOR_SCHEME_NAME = "SubMerge.hidden-color-scheme"

# The package still works if the folder is renamed (e.g. to "0_SubMerge" so it
# sorts first in the context menus), so resolve the name at runtime.
PACKAGE = __name__.split(".")[0]

REGION_CHANGED = "submerge_changed"
REGION_ADDED = "submerge_added"
REGION_MOVED = "submerge_moved"
REGION_INLINE = "submerge_inline"
REGION_INLINE_MAJOR = "submerge_inline_major"
REGION_CURRENT = "submerge_current"
PHANTOM_GAPS = "submerge_gaps"

# ---------------------------------------------------------------------------
# Diff highlight scopes: Sublime defines eight scope names that every shipped
# color scheme gives a real color to natively, with no custom color scheme or
# merge step required - this is the officially documented way for
# View.add_regions() to get color, and what GitGutter, SublimeLinter and
# other region-marking plugins actually rely on:
#
#   region.redish   region.orangish  region.yellowish  region.greenish
#   region.cyanish  region.bluish    region.purplish   region.pinkish
#
# An earlier version of this file invented its own scope names
# ("submerge.line.changed" etc.) and relied on a generated
# ".hidden-color-scheme" file to give them color. That merge is documented to
# work for syntax-highlighted *text* (which is how the folder-comparison and
# metadata-report tabs get their color, and still do below), but is not
# guaranteed for add_regions() with a scope that exists nowhere else - and in
# practice does not reliably reach add_regions() at all in every environment.
# Using the built-in region.*ish names sidesteps that: they render correctly
# with zero configuration, in any color scheme, using colors that scheme's
# own author already chose to be visible against it.
#
# The trade-off: these eight scopes are also used by other plugins and by
# Sublime itself (bookmarks, git status, linters, ...), so SubMerge does not
# override their colors - doing so would recolor those other features too.
# What you get is your color scheme's own idea of "reddish"/"greenish"/etc,
# which is good enough to tell differences apart at a glance, but is not
# independently customizable the way the folder/metadata colors are.
# ---------------------------------------------------------------------------

SCOPE_ADDED = "region.greenish"
SCOPE_CHANGED = "region.yellowish"
SCOPE_INLINE = "region.orangish"
SCOPE_INLINE_MAJOR = "region.redish"
SCOPE_MOVED = "region.bluish"
SCOPE_CURRENT = "region.purplish"

# ---------------------------------------------------------------------------
# color presets
#
# These now apply to two things only: the folder-comparison / metadata-report
# tabs (custom "submerge.folder.*" scopes, confirmed to pick up custom colors
# via the merge described above, since that path is syntax-highlighted text)
# and the fill color of the artificial gap phantoms (plain inline CSS, no
# scope involved at all, so it is always reliable regardless of any of this).
#
# "colors" in the settings file always wins on a key-by-key basis - a preset
# just supplies whatever the person hasn't overridden themselves.
# ---------------------------------------------------------------------------

PRESETS = {
    "vivid": {
        "gap": "rgba(229,57,53,0.12)",
        "folder_identical": "#7E8B8B",
        "folder_metadata": "#8A7BC8",
        "folder_different": "#E69800",
        "folder_unique": "#E5533D",
        "folder_directory": "#4A90D9",
    },
    "classic": {
        "gap": "rgba(128,128,128,0.14)",
        "folder_identical": "#7E8B8B",
        "folder_metadata": "#8A7BC8",
        "folder_different": "#D9A400",
        "folder_unique": "#C75B39",
        "folder_directory": "#4A90D9",
    },
    "high_contrast": {
        "gap": "rgba(255,23,68,0.20)",
        "folder_identical": "#8C8C8C",
        "folder_metadata": "#B388FF",
        "folder_different": "#FFAB00",
        "folder_unique": "#FF5252",
        "folder_directory": "#2979FF",
    },
    "pastel": {
        "gap": "rgba(120,120,120,0.10)",
        "folder_identical": "#9E9E9E",
        "folder_metadata": "#B39DDB",
        "folder_different": "#E1B84A",
        "folder_unique": "#E39181",
        "folder_directory": "#90B8E0",
    },
    "colorblind_safe": {
        "gap": "rgba(213,94,0,0.14)",
        "folder_identical": "#8C8C8C",
        "folder_metadata": "#CC79A7",
        "folder_different": "#E69F00",
        "folder_unique": "#D55E00",
        "folder_directory": "#56B4E9",
    },
}

DEFAULT_PRESET = "vivid"
DEFAULT_COLORS = PRESETS[DEFAULT_PRESET]

# highlight_style values and the draw flags each one needs.
#   "background" - filled highlight (the classic look). The only style
#                   guaranteed to also show up in the minimap.
#   "underline"  - a solid colored underline; the text keeps its own syntax
#                   color, so this reads as "lighter touch" than a fill.
#   "squiggly"   - the same, but a wavy underline (spell-check style).
#
# There is deliberately no "recolor the text itself" option:
# View.add_regions() can fill, outline, or underline a region using its
# scope's colors, but it has no facility to change the rendered color of the
# text within it - only real syntax-scope assignment (tokenizing, the way an
# actual .sublime-syntax file colors code) can do that, and diff regions are
# computed dynamically per comparison, not fixed by a syntax file. Confirmed
# against a real installation: a scope with both foreground and background
# defined still shows nothing when add_regions() is asked to "just recolor
# the text" - the color has nowhere to attach without a fill, outline, or
# underline to carry it.
HIGHLIGHT_STYLES = ("background", "underline", "squiggly")


# window_id -> Session
_sessions = {}
_tick_running = False


def settings():
    return sublime.load_settings(SETTINGS_FILE)


def setting(key, default=None):
    return settings().get(key, default)


def options_from_settings():
    return CompareOptions(
        ignore_whitespace=bool(setting("ignore_whitespace", False)),
        ignore_all_whitespace=bool(setting("ignore_all_whitespace", False)),
        ignore_case=bool(setting("ignore_case", False)),
        ignore_blank_lines=bool(setting("ignore_blank_lines", False)),
        ignore_line_endings=bool(setting("ignore_line_endings", True)),
        intraline_mode=setting("intraline_mode", "word"),
        detect_moved=bool(setting("detect_moved_lines", True)),
        moved_min_length=int(setting("moved_min_length", 3) or 1),
    )


# ---------------------------------------------------------------------------
# colors
# ---------------------------------------------------------------------------

def _resolved_colors():
    preset_name = setting("color_preset", DEFAULT_PRESET)
    base = dict(PRESETS.get(preset_name, PRESETS[DEFAULT_PRESET]))
    base.update(dict(setting("colors", {}) or {}))
    return base


def _highlight_style():
    style = setting("highlight_style", "background")
    return style if style in HIGHLIGHT_STYLES else "background"


def draw_flags_for_diff(hide_in_minimap=False):
    """Flags for a line/inline difference region, matching highlight_style."""
    style = _highlight_style()
    if style == "underline":
        flags = sublime.DRAW_SOLID_UNDERLINE | sublime.DRAW_NO_FILL | \
            sublime.DRAW_NO_OUTLINE
    elif style == "squiggly":
        flags = sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL | \
            sublime.DRAW_NO_OUTLINE
    else:
        flags = sublime.DRAW_NO_OUTLINE
    if hide_in_minimap:
        flags |= sublime.HIDDEN
    return flags


def _current_hunk_flags():
    """The "you are here" marker is an outline box only when the regular
    diffs are filled backgrounds - an outline reads as "here" layered on top
    of that fill. With underline/squiggly, nothing is filled, so an outline
    box would be the only boxed thing on screen and reads as a stray
    highlight rather than a position marker; match the chosen style instead
    so it's drawn the same way as everything else, just in its own color
    (region.purplish)."""
    if _highlight_style() == "background":
        return sublime.DRAW_NO_FILL
    return draw_flags_for_diff()



def _folder_rule(scope, name, bold=False):
    colors = _resolved_colors()
    rule = {"scope": scope, "foreground": colors.get(name, DEFAULT_COLORS[name])}
    if bold:
        rule["font_style"] = "bold"
    return rule


def write_color_scheme(force=False):
    """Generate Packages/User/SubMerge.hidden-color-scheme.

    This now covers only the folder-comparison and metadata-report tabs:
    custom "submerge.folder.*" scopes applied through syntax highlighting,
    which Sublime's hidden-color-scheme merge reliably reaches (unlike
    add_regions(), see the scope constants above). Line and inline diff
    highlighting no longer needs this file at all - it uses the built-in
    region.*ish scopes, which already have color in every color scheme."""
    rules = [
        _folder_rule("submerge.folder.identical", "folder_identical"),
        _folder_rule("submerge.folder.metadata", "folder_metadata"),
        _folder_rule("submerge.folder.different", "folder_different"),
        _folder_rule("submerge.folder.unique", "folder_unique"),
        _folder_rule("submerge.folder.directory", "folder_directory", bold=True),
    ]
    data = {
        "name": "SubMerge",
        "author": "SubMerge",
        "variables": {},
        "globals": {},
        "rules": rules,
    }
    body = json.dumps(data, indent=4, sort_keys=True)
    path = os.path.join(sublime.packages_path(), "User", COLOR_SCHEME_NAME)
    try:
        if not force and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                if handle.read() == body:
                    return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
    except OSError as exc:
        print("SubMerge: unable to write color scheme: %s" % exc)
    return path


# ---------------------------------------------------------------------------
# layout helpers
# ---------------------------------------------------------------------------

ARROW = "\u2194"   # LEFT RIGHT ARROW - the separator in every SubMerge title


def join_names(names):
    """'A' / 'A ↔ B' / 'A ↔ B ↔ C' - the shared naming convention for every
    tab and window SubMerge generates (folder results, metadata reports,
    table view). Real, file-backed comparison tabs cannot use this: Sublime
    always displays a saved file's own basename for its tab and ignores
    View.set_name() in that case, so this only applies to generated views."""
    return (" %s " % ARROW).join(names)


def title_for(prefix, names):
    joined = join_names(names)
    return "SubMerge: %s%s" % (prefix, joined) if prefix else "SubMerge: %s" % joined


def bump_color_scheme(view):
    """Force this view to re-resolve its color scheme, hidden-color-scheme
    overlay included.

    Sublime can cache a view's resolved scheme independently of when the
    underlying hidden-color-scheme *file* on disk changes - syntax-highlighted
    scopes (like the folder-result and metadata-report tabs use) are
    re-evaluated on every redraw and always pick up a fresh file, but scopes
    applied dynamically through add_regions() are not guaranteed to. Setting
    color_scheme to its own current value is the documented way to make
    Sublime rebuild that cache for one view. Call this on a view before
    adding any diff-highlight regions to it."""
    vs = view.settings()
    current = vs.get("color_scheme")
    if current:
        vs.set("color_scheme", current)


def columns_layout(count):
    if count <= 1:
        return {"cols": [0.0, 1.0], "rows": [0.0, 1.0],
                "cells": [[0, 0, 1, 1]]}
    if count == 3:
        cols = [0.0, 0.34, 0.67, 1.0]
    else:
        cols = [0.0, 0.5, 1.0]
    cells = [[i, 0, i + 1, 1] for i in range(count)]
    return {"cols": cols, "rows": [0.0, 1.0], "cells": cells}


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------

class Session(object):

    def __init__(self, window, views, mode="text", sources=None):
        self.window = window
        self.views = views
        self.view_ids = [v.id() for v in views]
        self.pane_count = len(views)
        self.mode = mode                     # "text" | "table"
        self.sources = sources or []         # original paths, when known
        self.alignment = None
        self.current_hunk = 0
        self._navigated = False   # don't show the current-hunk marker until
                                  # the person actually navigates to one
        self.previous_layout = window.get_layout()
        self._phantom_sets = {}
        self._last_viewport = {}
        self._syncing = False
        self._saved_view_settings = {}

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        # Belt and suspenders against a stale cached scheme: rewrite the
        # overlay file now (cheap, and guarantees it reflects the latest
        # settings even if something upstream skipped a write), then bump
        # every pane so it re-resolves against the fresh file rather than
        # whatever it may have cached earlier in the session.
        write_color_scheme(force=True)
        self.window.set_layout(columns_layout(self.pane_count))
        for index, view in enumerate(self.views):
            self.window.set_view_index(view, index, 0)
            self._prepare_view(view, index)
        self.refresh()
        self.window.focus_view(self.views[0])
        _start_ticker()
        # Sublime always shows a saved file's own basename in its tab and
        # ignores View.set_name() for it, so a shared "A ↔ B" title cannot be
        # applied to the tabs themselves (see title_for's docstring). The
        # status bar is the one place SubMerge can still show it.
        sublime.status_message(self.title())

    def title(self):
        names = []
        for index, view in enumerate(self.views):
            path = self.sources[index] if index < len(self.sources) else None
            names.append(os.path.basename(path) if path else
                         (view.name() or "untitled") if view.is_valid() else
                         "untitled")
        prefix = "table \u2014 " if self.mode == "table" else ""
        return title_for(prefix, names)

    def _prepare_view(self, view, index):
        bump_color_scheme(view)
        vs = view.settings()
        self._saved_view_settings[view.id()] = {
            "word_wrap": vs.get("word_wrap"),
            "draw_white_space": vs.get("draw_white_space"),
            "scroll_past_end": vs.get("scroll_past_end"),
        }
        vs.set("submerge_active", True)
        vs.set("submerge_pane", index)
        vs.set("submerge_pane_count", self.pane_count)
        if setting("disable_word_wrap", True):
            vs.set("word_wrap", False)
        if setting("scroll_past_end", True):
            vs.set("scroll_past_end", True)
        vs.set("highlight_line", True)

    def end(self, restore_layout=True):
        for view in self.alive_views():
            for key in (REGION_CHANGED, REGION_ADDED, REGION_MOVED,
                        REGION_INLINE, REGION_INLINE_MAJOR, REGION_CURRENT):
                view.erase_regions(key)
            ps = self._phantom_sets.get(view.id())
            if ps:
                ps.update([])
            saved = self._saved_view_settings.get(view.id(), {})
            vs = view.settings()
            for key, value in saved.items():
                if value is None:
                    vs.erase(key)
                else:
                    vs.set(key, value)
            for key in ("submerge_active", "submerge_pane", "submerge_pane_count"):
                vs.erase(key)
        self._phantom_sets.clear()
        if not restore_layout:
            return
        mode = setting("layout_on_close", "restore")
        try:
            if mode == "single":
                self.window.run_command("set_layout", columns_layout(1))
            elif mode == "restore" and self.previous_layout:
                self.window.set_layout(self.previous_layout)
        except Exception:
            pass

    def alive_views(self):
        out = []
        for view in self.views:
            if view.is_valid():
                out.append(view)
        return out

    def is_alive(self):
        return len(self.alive_views()) == self.pane_count

    def pane_of(self, view):
        try:
            return self.view_ids.index(view.id())
        except ValueError:
            return None

    # -- diffing ------------------------------------------------------------

    def texts(self):
        return [v.substr(sublime.Region(0, v.size())) for v in self.views]

    def refresh(self):
        if not self.is_alive():
            return
        pane_lines = [split_lines(t) for t in self.texts()]
        self.alignment = Alignment(pane_lines, options_from_settings())
        self.render()

    # -- rendering ----------------------------------------------------------

    def _phantom_set(self, view):
        ps = self._phantom_sets.get(view.id())
        if ps is None:
            ps = sublime.PhantomSet(view, PHANTOM_GAPS)
            self._phantom_sets[view.id()] = ps
        return ps

    def render(self):
        align = self.alignment
        if align is None:
            return
        draw_flags = draw_flags_for_diff(hide_in_minimap=bool(
            setting("hide_diff_in_minimap", False)))
        gutter_icon = setting("gutter_icon", "dot") or ""

        # "auto"   - a line that only differs in part gets just that part
        #            highlighted; a line with no counterpart gets the full line
        # "always" - always paint the whole line as well
        # "never"  - never paint the whole line
        line_mode = setting("highlight_changed_line", "auto")
        moved_map = getattr(align, "moved", None) or \
            [{} for _ in range(self.pane_count)]

        # A line where more than this fraction of its characters differ gets
        # the more intense "major" inline color instead of the normal one -
        # a typo-sized edit and a rewritten line no longer look identical.
        graduated = bool(setting("graduated_inline_highlight", True))
        threshold = float(setting("inline_intensity_threshold", 0.4) or 0.4)

        for pane, view in enumerate(self.views):
            if not view.is_valid():
                continue
            changed, added, moved = [], [], []
            inline_minor, inline_major = [], []
            total_lines = view.rowcol(view.size())[0] + 1

            for row in range(len(align.rows)):
                if align.row_kind[row] != CHANGED:
                    continue
                line = align.rows[row][pane]
                if line is None or line >= total_lines:
                    continue
                region = self._full_line(view, line)
                if line in moved_map[pane]:
                    moved.append(region)
                    continue
                others_missing = any(align.rows[row][p] is None
                                     for p in range(self.pane_count) if p != pane)
                if others_missing:
                    # This pane has content the others don't - added, relative
                    # to them.  The gap in the other pane(s) is the "removed"
                    # side of the same story.
                    added.append(region)
                    continue
                if line_mode == "never":
                    continue
                if line_mode == "auto" and align.inline[pane].get(line):
                    # Only part of the line differs - the intra-line regions
                    # below are the whole highlight for this line.
                    continue
                changed.append(region)

            for line, ranges in align.inline[pane].items():
                if line >= total_lines:
                    continue
                start = view.text_point(line, 0)
                line_len = view.line(start).size()
                changed_chars = sum(min(b, line_len) - min(a, line_len)
                                    for a, b in ranges)
                major = graduated and line_len > 0 and \
                    (changed_chars / line_len) >= threshold
                bucket = inline_major if major else inline_minor
                for a, b in ranges:
                    a = min(a, line_len)
                    b = min(b, line_len)
                    if b > a:
                        bucket.append(sublime.Region(start + a, start + b))

            view.add_regions(REGION_CHANGED, changed, SCOPE_CHANGED,
                             gutter_icon, draw_flags)
            view.add_regions(REGION_ADDED, added, SCOPE_ADDED,
                             gutter_icon, draw_flags)
            view.add_regions(REGION_MOVED, moved, SCOPE_MOVED,
                             gutter_icon, draw_flags)
            view.add_regions(REGION_INLINE, inline_minor, SCOPE_INLINE, "",
                             draw_flags)
            view.add_regions(REGION_INLINE_MAJOR, inline_major,
                             SCOPE_INLINE_MAJOR, "", draw_flags)

            self._render_gaps(view, pane, total_lines)

        if self._navigated:
            self.highlight_current_hunk(scroll=False)

    def _full_line(self, view, line):
        """Region covering the line *including* its newline so the highlight is
        drawn all the way to the right edge of the pane."""
        start = view.text_point(line, 0)
        region = view.full_line(start)
        if region.b > view.size():
            region = sublime.Region(region.a, view.size())
        return region

    def _render_gaps(self, view, pane, total_lines):
        ps = self._phantom_set(view)
        if not setting("show_gaps", True):
            ps.update([])
            return
        color = _resolved_colors().get("gap", DEFAULT_COLORS["gap"])
        phantoms = []
        for line, size in sorted(self.alignment.gaps[pane].items()):
            if size <= 0:
                continue
            html = _gap_html(size, color)
            if line == 0:
                # There is no "block above the first line" layout, so the very
                # first gap is rendered inline on line 0 (see README limits).
                point = 0
                layout = sublime.LAYOUT_INLINE
            else:
                anchor = min(line - 1, total_lines - 1)
                point = view.line(view.text_point(anchor, 0)).b
                layout = sublime.LAYOUT_BLOCK
            phantoms.append(sublime.Phantom(sublime.Region(point, point),
                                            html, layout))
        ps.update(phantoms)

    # -- hunk navigation ----------------------------------------------------

    def hunks(self):
        return self.alignment.hunks if self.alignment else []

    def goto_hunk(self, index, focus_view=None):
        hunks = self.hunks()
        if not hunks:
            sublime.status_message("SubMerge: no differences")
            return
        index = max(0, min(index, len(hunks) - 1))
        self.current_hunk = index
        self._navigated = True
        self.highlight_current_hunk(scroll=True, focus_view=focus_view)
        note = ""
        if getattr(self.alignment, "hunk_is_moved_only", None) and \
                self.alignment.hunk_is_moved_only(hunks[index]):
            note = "  (moved lines)"
        sublime.status_message("SubMerge: difference %d of %d%s"
                               % (index + 1, len(hunks), note))

    def next_hunk(self, view=None):
        hunks = self.hunks()
        if not hunks:
            sublime.status_message("SubMerge: no differences")
            return
        row = self._current_row(view)
        for hunk in hunks:
            if hunk.start_row > row:
                return self.goto_hunk(hunk.index, view)
        self.goto_hunk(0 if setting("wrap_navigation", True) else len(hunks) - 1, view)

    def prev_hunk(self, view=None):
        hunks = self.hunks()
        if not hunks:
            sublime.status_message("SubMerge: no differences")
            return
        row = self._current_row(view)
        for hunk in reversed(hunks):
            if hunk.end_row <= row:
                return self.goto_hunk(hunk.index, view)
        self.goto_hunk(len(hunks) - 1 if setting("wrap_navigation", True) else 0, view)

    def _current_row(self, view=None):
        view = view or self.window.active_view()
        pane = self.pane_of(view) if view else None
        if pane is None:
            pane = 0
            view = self.views[0]
        line = view.rowcol(view.sel()[0].begin())[0] if len(view.sel()) else 0
        row = self.alignment.row_of_line(pane, line)
        return row if row is not None else 0

    def hunk_under_cursor(self, view):
        pane = self.pane_of(view)
        if pane is None or not len(view.sel()):
            return None
        line = view.rowcol(view.sel()[0].begin())[0]
        hunk = self.alignment.hunk_for_line(pane, line)
        if hunk is None:
            # The cursor may sit next to a gap; use the nearest hunk boundary.
            row = self.alignment.row_of_line(pane, line)
            if row is not None:
                for h in self.hunks():
                    if h.start_row <= row + 1 and row - 1 < h.end_row:
                        return h
        return hunk

    def highlight_current_hunk(self, scroll=True, focus_view=None):
        hunks = self.hunks()
        for view in self.alive_views():
            view.erase_regions(REGION_CURRENT)
        if not hunks:
            return
        hunk = hunks[max(0, min(self.current_hunk, len(hunks) - 1))]
        for pane, view in enumerate(self.views):
            if not view.is_valid():
                continue
            lines = self.alignment.lines_in_hunk(hunk, pane)
            regions = [self._full_line(view, l) for l in lines]
            if regions:
                view.add_regions(REGION_CURRENT, regions, SCOPE_CURRENT, "",
                                 _current_hunk_flags())
            if scroll:
                target = lines[0] if lines else \
                    self.alignment.next_present_line(pane, hunk.start_row)
                target = min(target, view.rowcol(view.size())[0])
                point = view.text_point(target, 0)
                if setting("sync_selection", True) or view == focus_view:
                    view.sel().clear()
                    view.sel().add(sublime.Region(point, point))
                view.show_at_center(point)

    # -- merging ------------------------------------------------------------

    def merging_allowed(self):
        if self.mode == "table":
            sublime.status_message(
                "SubMerge: merging is disabled in CSV/TSV table view")
            return False
        return True

    def copy_hunk(self, hunk, source_pane, target_pane):
        if not self.merging_allowed():
            return False
        align = self.alignment
        target = self.views[target_pane]
        if target.is_read_only():
            sublime.error_message("SubMerge: the target tab is read only.")
            return False

        src_lines = align.lines_in_hunk(hunk, source_pane)
        payload = "\n".join(align.pane_lines[source_pane][i] for i in src_lines)

        tgt_lines = align.lines_in_hunk(hunk, target_pane)
        if tgt_lines:
            args = {
                "start_line": tgt_lines[0],
                "end_line": tgt_lines[-1] + 1,
                "text": payload,
                "insert": False,
                "delete": not src_lines,
            }
        elif not src_lines:
            sublime.status_message("SubMerge: nothing to copy")
            return False
        else:
            anchor = align.next_present_line(target_pane, hunk.start_row)
            args = {
                "start_line": anchor,
                "end_line": anchor,
                "text": payload,
                "insert": True,
            }
        target.run_command("submerge_apply_patch", args)
        self.refresh()
        return True

    def copy_all(self, source_pane, target_pane):
        if not self.merging_allowed():
            return
        count = 0
        for hunk in list(reversed(self.hunks())):
            if self.copy_hunk_quiet(hunk, source_pane, target_pane):
                count += 1
        self.refresh()
        sublime.status_message("SubMerge: copied %d difference(s)" % count)

    def copy_hunk_quiet(self, hunk, source_pane, target_pane):
        align = self.alignment
        target = self.views[target_pane]
        if target.is_read_only():
            return False
        src_lines = align.lines_in_hunk(hunk, source_pane)
        payload = "\n".join(align.pane_lines[source_pane][i] for i in src_lines)
        tgt_lines = align.lines_in_hunk(hunk, target_pane)
        if tgt_lines:
            args = {"start_line": tgt_lines[0], "end_line": tgt_lines[-1] + 1,
                    "text": payload, "insert": False, "delete": not src_lines}
        elif not src_lines:
            return False
        else:
            anchor = align.next_present_line(target_pane, hunk.start_row)
            args = {"start_line": anchor, "end_line": anchor,
                    "text": payload, "insert": True}
        target.run_command("submerge_apply_patch", args)
        return True

    # -- scroll synchronization --------------------------------------------

    def sync_tick(self):
        if self._syncing or not setting("sync_scroll", True):
            return
        if not self.is_alive():
            return
        driver = self.window.active_view()
        pane = self.pane_of(driver) if driver else None
        if pane is None:
            return
        position = driver.viewport_position()
        if self._last_viewport.get(driver.id()) == position:
            return
        self._syncing = True
        try:
            self._propagate(pane, position)
        finally:
            for view in self.alive_views():
                self._last_viewport[view.id()] = view.viewport_position()
            self._syncing = False

    def _propagate(self, source_pane, position):
        sync_x = bool(setting("sync_horizontal_scroll", True))
        for pane, view in enumerate(self.views):
            if pane == source_pane or not view.is_valid():
                continue
            y = self._map_y(source_pane, pane, position[1])
            if y is None:
                continue
            x = position[0] if sync_x else view.viewport_position()[0]
            view.set_viewport_position((x, y), False)

    def _map_y(self, source_pane, target_pane, y):
        align = self.alignment
        if align is None:
            return None
        source = self.views[source_pane]
        target = self.views[target_pane]
        line_height = source.line_height() or 1.0

        point = source.layout_to_text((0.0, max(0.0, y)))
        line = source.rowcol(point)[0]
        line_y = source.text_to_layout(source.text_point(line, 0))[1]
        delta = y - line_y

        row = align.row_of_line(source_pane, line)
        if row is None:
            return None

        target_line = align.rows[row][target_pane]
        if target_line is not None:
            base_y = target.text_to_layout(target.text_point(target_line, 0))[1]
        else:
            prev_line = align.prev_present_line(target_pane, row)
            if prev_line is None:
                base_y = 0.0
                offset_rows = row
            else:
                prev_row = align.row_of_line(target_pane, prev_line)
                base_y = target.text_to_layout(
                    target.text_point(prev_line, 0))[1] + line_height
                offset_rows = row - prev_row - 1
            base_y += max(0, offset_rows) * target.line_height()
        return max(0.0, base_y + delta)


def _gap_html(lines, color):
    rows = "".join('<div class="l">&nbsp;</div>' for _ in range(lines))
    return (
        '<body id="submerge-gap">'
        '<style>'
        'html, body {{ margin: 0; padding: 0; }}'
        '.g {{ background-color: {color}; }}'
        '.l {{ margin: 0; padding: 0; }}'
        '</style>'
        '<div class="g">{rows}</div>'
        '</body>'
    ).format(color=color, rows=rows)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def get_session(window):
    if window is None:
        return None
    session = _sessions.get(window.id())
    if session and not session.is_alive():
        session.end(restore_layout=False)
        _sessions.pop(window.id(), None)
        return None
    return session


def session_for_view(view):
    if view is None:
        return None
    window = view.window()
    session = get_session(window)
    if session and session.pane_of(view) is not None:
        return session
    for candidate in _sessions.values():
        if candidate.pane_of(view) is not None:
            return candidate
    return None


def start_session(window, views, mode="text", sources=None):
    end_session(window)
    session = Session(window, views, mode=mode, sources=sources)
    _sessions[window.id()] = session
    session.start()
    return session


def end_session(window, restore_layout=True):
    session = _sessions.pop(window.id(), None) if window else None
    if session:
        session.end(restore_layout=restore_layout)
    return session is not None


def all_sessions():
    return list(_sessions.values())


def _start_ticker():
    global _tick_running
    if _tick_running:
        return
    _tick_running = True
    _tick()


def _tick():
    global _tick_running
    for window_id, session in list(_sessions.items()):
        if not session.is_alive():
            session.end(restore_layout=False)
            _sessions.pop(window_id, None)
            continue
        try:
            session.sync_tick()
        except Exception as exc:  # never let the ticker die
            print("SubMerge: sync error: %s" % exc)
    if _sessions:
        interval = int(setting("sync_interval_ms", 60) or 60)
        sublime.set_timeout(_tick, max(20, interval))
    else:
        _tick_running = False
