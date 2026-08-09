"""
SubMerge - a WinMerge-style file and folder comparison plugin for Sublime Text 4.

Entry point: commands + event listeners.  The diff engine lives in
submerge_core.py, the rendering/session layer in submerge_session.py, folder
comparison in submerge_folder.py, metadata handling in submerge_metadata.py and
CSV/TSV rendering in submerge_table.py.
"""

import os
import tempfile
import urllib.parse
import urllib.request
import webbrowser

import sublime
import sublime_plugin

from .modules import submerge_core as core
from .modules import submerge_docs as docs
from .modules import submerge_folder as folders
from .modules import submerge_metadata as metadata
from .modules import submerge_session as sessions
from .modules.submerge_core import MAX_PANES, PANE_LETTERS
from .modules.submerge_session import (
    PACKAGE, SETTINGS_FILE, setting, settings)
from .modules import submerge_table as table

PLUGIN_VERSION = "1.1.1"

# Rewritten in place each time the guide is opened; see the command below.
GUIDE_FILENAME = "SubMerge-user-guide.html"

REQUIRED_VERSIONS = {
    "submerge_core": (core, 3),
    "submerge_session": (sessions, 7),
    "submerge_folder": (folders, 3),
    "submerge_metadata": (metadata, 2),
    "submerge_table": (table, 2),
    "submerge_docs": (docs, 2),
}
_marked = []          # list of view ids marked with "Mark for Compare"
_marked_paths = []    # list of side bar paths marked for comparison
_metadata_window_id = None   # window most recently used for metadata reports
_pending_refresh = 0


# ---------------------------------------------------------------------------
# plugin lifecycle
# ---------------------------------------------------------------------------

def _check_modules():
    """Sublime reloads a package's top level plugin file when it changes, but
    does not always re-execute the sub-modules that file imports.  Overwriting
    the package while Sublime is running can therefore leave a new SubMerge.py
    talking to old sub-modules - and since most sub-modules keep their public
    function names stable across changes, that usually fails *silently*
    rather than with an error: settings, menu items and commands that depend
    on new behavior in a stale module just quietly keep doing what the old
    code did. Detect that and say so plainly, listing every stale module
    rather than only the first one found."""
    stale = []
    for name, (module, required) in REQUIRED_VERSIONS.items():
        found = getattr(module, "VERSION", 0)
        if found < required:
            stale.append("%s (found version %s, need %s)"
                         % (name, found, required))
    if not stale:
        return True
    message = (
        "SubMerge: mismatched modules - Sublime is still running an older "
        "copy of part of this package:\n  "
        + "\n  ".join(stale)
        + "\nQuit Sublime Text completely (not just close the window) and "
        "start it again."
    )
    print(message)
    sublime.status_message("SubMerge: mismatched modules - restart Sublime Text")
    return False


def plugin_loaded():
    sessions.write_color_scheme(force=True)
    settings().add_on_change("submerge", _on_settings_changed)
    _check_modules()


def plugin_unloaded():
    settings().clear_on_change("submerge")
    # Not just end() on each: the registry has to be emptied and the ticker
    # stopped, or this module's 60 ms timer outlives the reload.
    sessions.shutdown()


def _on_settings_changed():
    sessions.write_color_scheme()
    for session in sessions.all_sessions():
        session.refresh()


# ---------------------------------------------------------------------------
# sources - something that can be compared (an open view or a path on disk)
# ---------------------------------------------------------------------------

class Source(object):

    def __init__(self, path=None, view=None):
        self.path = path or (view.file_name() if view else None)
        self.view = view

    def label(self):
        if self.view is not None and not self.view.file_name():
            return self.view.name() or "untitled"
        return os.path.basename(self.path or "untitled")

    def is_dirty(self):
        return self.view is not None and self.view.is_dirty()

    def text(self):
        if self.view is not None and self.view.is_valid():
            return self.view.substr(sublime.Region(0, self.view.size()))
        if self.path:
            return _read_text(self.path)
        return None


def _read_text(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        sublime.error_message("SubMerge: cannot read %s\n\n%s" % (path, exc))
        return None
    if b"\x00" in data[:8192]:
        sublime.error_message(
            "SubMerge: %s looks like a binary file.\n\n"
            "Sublime Text cannot display a binary diff." % os.path.basename(path))
        return None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _normalize_paths(args):
    """Sidebar commands hand us `files`, `dirs` or `paths`."""
    out = []
    for key in ("files", "dirs", "paths"):
        value = args.get(key)
        if value:
            out.extend(value)
    seen = set()
    unique = []
    for path in out:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _sources_from_paths(window, paths):
    sources = []
    for path in paths:
        sources.append(Source(path=path, view=window.find_open_file(path)))
    return sources


def _view_at(window, group, index):
    """The view a tab context menu was invoked on, else the active view."""
    if group >= 0 and index >= 0:
        views = window.views_in_group(group)
        if index < len(views):
            return views[index]
    return window.active_view()


def _selected_tab_views(window):
    """Views for the tabs the user has selected in the tab bar.

    Window.selected_sheets() needs Sublime Text build 4050 or newer; older
    builds simply never offer the "compare selected tabs" commands.
    """
    if not hasattr(window, "selected_sheets"):
        return []
    try:
        sheets = window.selected_sheets()
    except Exception:
        return []
    views = []
    for sheet in sheets:
        view = sheet.view() if hasattr(sheet, "view") else None
        if view is not None and view.is_valid():
            views.append(view)
    return views


def _comparable_tab_views(window):
    views = [v for v in _selected_tab_views(window)
             if not folders.is_folder_view(v)
             and not v.settings().get("submerge_metadata_view")]
    return views if 2 <= len(views) <= MAX_PANES else []


def _folder_view(window, group=-1, index=-1):
    """The folder comparison result a menu item was invoked on, if any."""
    view = _view_at(window, group, index)
    if folders.is_folder_view(view):
        return view
    return None


def _describe(view):
    name = view.file_name()
    if name:
        return os.path.basename(name)
    return view.name() or "untitled"


# ---------------------------------------------------------------------------
# starting a comparison
# ---------------------------------------------------------------------------

def _configure_window(window, sidebar=True, minimap=True):
    """Chrome for a window SubMerge just created.  Only ever applied to new
    windows - an existing window the user set up themselves is left alone."""
    if window is None:
        return window
    if not sidebar:
        try:
            window.set_sidebar_visible(False)
        except Exception:
            pass
    if not minimap:
        try:
            window.set_minimap_visible(False)
        except Exception:
            pass
    return window


def _new_window(single_column=False, sidebar=True, minimap=True):
    sublime.run_command("new_window")
    window = sublime.active_window()
    if window is None:
        return None
    if single_column:
        try:
            window.set_layout(sessions.columns_layout(1))
        except Exception:
            pass
    return _configure_window(window, sidebar=sidebar, minimap=minimap)


def _hide_sidebar():
    return bool(setting("new_window_hide_sidebar", True))


def _target_window(window, kind="files"):
    """Honor the "open comparisons in a new window" setting.

    `kind` is "files" or "folders"; a folder result is a single generated tab,
    so it follows the report chrome rather than the comparison chrome.
    """
    if not setting("compare_in_new_window", True):
        return window
    if kind == "folders":
        hide_minimap = bool(setting("report_window_hide_minimap", True))
    else:
        hide_minimap = bool(setting("new_window_hide_minimap", False))
    fresh = _new_window(sidebar=not _hide_sidebar(), minimap=not hide_minimap)
    return fresh if fresh and fresh.id() != window.id() else window


def _folder_target_window(window):
    return _target_window(window, kind="folders")


def _report_window(preferred):
    """Where a metadata report should open.

    A side-by-side comparison turns its window into two or three narrow
    columns, which is a poor place for a wide table, so by default the report
    avoids any window that is currently running a comparison.

      "auto"    - the window the report was requested from, unless that window
                  is showing a comparison; then a single column window
      "new"     - always a separate single column window
      "current" - wherever the request came from, comparison or not
    """
    global _metadata_window_id
    mode = setting("metadata_report_window", "auto")

    if mode == "current":
        return preferred

    if mode == "auto" and preferred is not None and \
            sessions.get_session(preferred) is None:
        return preferred

    # Reuse the report window from last time rather than piling up windows.
    if _metadata_window_id is not None:
        for window in sublime.windows():
            if window.id() == _metadata_window_id and \
                    sessions.get_session(window) is None:
                return window

    window = _new_window(
        single_column=True,
        sidebar=not _hide_sidebar(),
        minimap=not bool(setting("report_window_hide_minimap", True)),
    ) or preferred
    if window is not None:
        _metadata_window_id = window.id()
    return window


def _metadata_fields():
    return metadata.comparable_fields(
        setting("metadata_fields", None),
        bool(setting("ignore_line_endings", True)))


def begin_comparison(window, sources):
    """Diff first, and only build the side-by-side layout if it is useful."""
    if not _check_modules():
        sublime.error_message(
            "SubMerge: part of this package is still loaded from an older "
            "copy.\n\nQuit Sublime Text completely and start it again.")
        return
    if not 2 <= len(sources) <= MAX_PANES:
        sublime.error_message("SubMerge: choose two or three files to compare.")
        return

    texts = [source.text() for source in sources]
    if any(text is None for text in texts):
        return

    table_mode = _table_mode(sources)
    alignment = core.compare_texts(texts, sessions.options_from_settings())

    # Equivalent to alignment.identical, but works even against an older
    # engine that predates that property.
    if not alignment.hunks:
        _handle_identical(window, sources)
        return

    target = _target_window(window)
    if table_mode:
        _start_table_comparison(target, sources, texts)
    else:
        _start_text_comparison(target, sources)

    if setting("compare_metadata", False) and \
            setting("metadata_report_always", False):
        _open_metadata_report(window, sources, content_identical=False)


def _handle_identical(window, sources):
    paths = [source.path for source in sources]

    if setting("compare_metadata", False) and all(paths) and \
            not any(s.is_dirty() for s in sources):
        metas = [metadata.collect(path) for path in paths]
        differing = metadata.differing_fields(metas, _metadata_fields())
        if differing:
            result = sublime.yes_no_cancel_dialog(
                "SubMerge\n\nThe file contents are identical, but the file "
                "metadata differs.\n\nOpen a metadata comparison tab?",
                yes_title="Yes",
                no_title="No"
                )
            if result == sublime.DIALOG_YES:
                _open_metadata_report(window, sources,
                                      content_identical=True, metas=metas)
            return

    sublime.message_dialog(
        "SubMerge\n\nThe files are identical.\n\n"
        "No comparison tabs were opened.")
    sublime.status_message("SubMerge: files are identical")


def _start_text_comparison(window, sources):
    views = []
    for source in sources:
        view = None
        if source.view is not None and source.view.is_valid() and \
                source.view.window() and \
                source.view.window().id() == window.id():
            view = source.view
        elif source.path:
            view = window.find_open_file(source.path) or \
                window.open_file(source.path)
        elif source.view is not None:
            # An unsaved buffer cannot be moved between windows, so compare a
            # detached copy of it instead.
            view = window.new_file()
            view.set_name(sessions.title_for("copy \u2014 ", [source.label()]))
            view.set_scratch(True)
            view.settings().set("submerge_generated", True)
            view.run_command("submerge_replace_all", {"text": source.text()})
        if view is None:
            sublime.error_message("SubMerge: cannot open %s" % source.label())
            return
        views.append(view)
    _when_loaded(window, views, sources=sources)


def _when_loaded(window, views, attempts=0, sources=None):
    if any(v is None or v.is_loading() for v in views):
        if attempts > 100:
            sublime.error_message("SubMerge: timed out waiting for files to load.")
            return
        sublime.set_timeout(
            lambda: _when_loaded(window, views, attempts + 1, sources), 50)
        return
    sessions.start_session(window, views, mode="text",
                           sources=[s.path for s in (sources or [])])


# -- CSV / TSV table view ---------------------------------------------------

def _table_mode(sources):
    if not setting("csv_table_view", False):
        return False
    extras = setting("csv_extra_extensions", [])
    return all(table.is_table_file(source.path, extras) for source in sources)


def _table_options():
    return {
        "delimiter": setting("csv_delimiter", "auto"),
        "max_column_width": setting("csv_max_column_width", 40),
        "min_column_width": setting("csv_min_column_width", 3),
        "wrap_columns": setting("csv_wrap_columns", True),
        "row_numbers": setting("csv_row_numbers", True),
        "header_rule": setting("csv_header_rule", True),
    }


def _start_table_comparison(window, sources, texts):
    rendered, delimiter = table.render_all(
        texts, [s.path for s in sources], _table_options())
    views = []
    for source, text in zip(sources, rendered):
        view = window.new_file()
        view.set_name(sessions.title_for("table \u2014 ", [source.label()]))
        view.set_scratch(True)
        view.settings().set("word_wrap", False)
        view.settings().set("submerge_table_view", True)
        view.settings().set("submerge_generated", True)
        view.settings().set("submerge_source_path", source.path)
        view.run_command("submerge_replace_all", {"text": text})
        view.set_read_only(True)
        views.append(view)
    sessions.start_session(window, views, mode="table",
                           sources=[s.path for s in sources])
    sublime.status_message(
        "SubMerge: table view (delimiter %r) - merging is disabled here"
        % delimiter)


# -- metadata report --------------------------------------------------------

def _open_metadata_report(window, sources, content_identical, metas=None):
    paths = [source.path for source in sources]
    if not all(paths):
        sublime.status_message(
            "SubMerge: metadata is only available for saved files")
        return None
    metas = metas or [metadata.collect(path) for path in paths]
    text = metadata.render_report(paths, metas, content_identical,
                                  _metadata_fields())
    window = _report_window(window)
    if window is None:
        return None
    view = window.new_file()
    sessions.bump_color_scheme(view)
    view.set_name(sessions.title_for(
        "metadata \u2014 ", [os.path.basename(p) for p in paths]))
    view.set_scratch(True)
    view.settings().set("word_wrap", False)
    view.settings().set("submerge_metadata_view", True)
    view.settings().set("submerge_generated", True)
    view.run_command("submerge_replace_all", {"text": text})
    view.set_read_only(True)
    try:
        view.assign_syntax(
            "Packages/%s/SubMergeMetadata.sublime-syntax" % PACKAGE)
    except Exception as exc:
        # Without the syntax this report renders as flat, uncolored text -
        # exactly what the generated color scheme exists to prevent.
        print("SubMerge: could not assign the metadata syntax: %s" % exc)
    window.focus_view(view)
    if hasattr(window, "bring_to_front"):
        try:
            window.bring_to_front()
        except Exception:
            pass
    return view


# ---------------------------------------------------------------------------
# comparison entry points
# ---------------------------------------------------------------------------

class SubmergeCompareFilesCommand(sublime_plugin.WindowCommand):
    """Side bar: compare 2 or 3 selected files."""

    def run(self, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.isfile(p)]
        if not 2 <= len(paths) <= MAX_PANES:
            sublime.error_message(
                "SubMerge: select two or three files to compare.")
            return
        begin_comparison(self.window, _sources_from_paths(self.window, paths))

    def is_visible(self, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.isfile(p)]
        return 2 <= len(paths) <= MAX_PANES

    def is_enabled(self, **kwargs):
        return self.is_visible(**kwargs)

    def description(self, **kwargs):
        count = len([p for p in _normalize_paths(kwargs) if os.path.isfile(p)])
        return "SubMerge: Compare %d Files" % count


class SubmergeCompareFoldersCommand(sublime_plugin.WindowCommand):
    """Side bar: compare 2 or 3 selected folders."""

    def run(self, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.isdir(p)]
        if not 2 <= len(paths) <= MAX_PANES:
            sublime.error_message(
                "SubMerge: select two or three folders to compare.")
            return
        window = self.window
        sublime.set_timeout_async(
            lambda: folders.open_folder_compare(
                window, paths, _folder_target_window), 0)

    def is_visible(self, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.isdir(p)]
        return 2 <= len(paths) <= MAX_PANES

    def is_enabled(self, **kwargs):
        return self.is_visible(**kwargs)

    def description(self, **kwargs):
        count = len([p for p in _normalize_paths(kwargs) if os.path.isdir(p)])
        return "SubMerge: Compare %d Folders" % count


def _marked_views():
    """The still-open views behind the marked view ids."""
    out = []
    for view_id in _marked:
        view = sublime.View(view_id)
        if view.is_valid():
            out.append(view)
    return out


class SubmergeMarkForCompareCommand(sublime_plugin.WindowCommand):
    """Tab / buffer context menu: remember this tab as a comparison source."""

    def run(self, group=-1, index=-1, add=False):
        view = _view_at(self.window, group, index)
        if view is None:
            return
        if view.id() in _marked:
            # Already marked - this entry reads "Remove ... from Comparison".
            _marked.remove(view.id())
            self._announce("unmarked %s" % _describe(view))
            return
        if not add:
            del _marked[:]
        _marked.append(view.id())
        del _marked[:-MAX_PANES]
        self._announce("marked %s"
                       % ", ".join(_describe(v) for v in _marked_views()))

    def _announce(self, what):
        remaining = len(_marked_views())
        if remaining:
            sublime.status_message("SubMerge: %s (%d marked)" % (what, remaining))
        else:
            sublime.status_message("SubMerge: %s (nothing marked)" % what)

    def description(self, group=-1, index=-1, add=False):
        view = _view_at(self.window, group, index)
        if view is not None and view.id() in _marked:
            return "SubMerge: Remove This Tab from Comparison"
        if add:
            return "SubMerge: Add to Comparison"
        return "SubMerge: Mark for Comparison"

    def is_visible(self, group=-1, index=-1, add=False):
        view = _view_at(self.window, group, index)
        marked = view is not None and view.id() in _marked
        if add:
            # The "add" entry doubles as the "remove" entry for a marked tab.
            return marked or len(_marked) >= 1
        return not marked


class SubmergeCompareWithMarkedCommand(sublime_plugin.WindowCommand):
    """Tab / buffer context menu: compare this tab with the marked tab(s)."""

    def run(self, group=-1, index=-1):
        view = _view_at(self.window, group, index)
        views = _marked_views()
        if view is not None and view.id() not in [v.id() for v in views]:
            views.append(view)
        views = views[:MAX_PANES]
        if len(views) < 2:
            sublime.error_message(
                "SubMerge: mark another tab first (SubMerge: Mark for "
                "Comparison).")
            return
        del _marked[:]
        begin_comparison(self.window, [Source(view=v) for v in views])

    def description(self, group=-1, index=-1):
        views = _marked_views()
        if len(views) == 1:
            return "SubMerge: Compare with '%s'" % _describe(views[0])
        if len(views) >= 2:
            return "SubMerge: Compare with %d Marked Tabs" % len(views)
        return "SubMerge: Compare with Marked Tab"

    def is_visible(self, group=-1, index=-1):
        return len(_marked) >= 1

    def is_enabled(self, group=-1, index=-1):
        return len(_marked) >= 1


class SubmergeCompareSelectedTabsCommand(sublime_plugin.WindowCommand):
    """Compare the 2 or 3 tabs currently selected in the tab bar.

    Select them with Ctrl-click (Cmd-click on macOS) or Shift-click, then use
    this from the tab or buffer context menu.
    """

    def run(self, group=-1, index=-1):
        views = _comparable_tab_views(self.window)
        if not views:
            sublime.error_message(
                "SubMerge: select two or three tabs first.\n\n"
                "Ctrl-click (Cmd-click on macOS) the tabs you want to "
                "compare, then run this command again.")
            return
        begin_comparison(self.window, [Source(view=v) for v in views])

    def is_visible(self, group=-1, index=-1):
        return bool(_comparable_tab_views(self.window))

    def is_enabled(self, group=-1, index=-1):
        return self.is_visible(group, index)

    def description(self, group=-1, index=-1):
        count = len(_comparable_tab_views(self.window))
        if count:
            return "SubMerge: Compare %d Selected Tabs" % count
        return "SubMerge: Compare Selected Tabs"


class SubmergeMarkPathForCompareCommand(sublime_plugin.WindowCommand):
    """Side bar: remember the selected file(s) or folder(s) for comparison."""

    def run(self, add=False, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.exists(p)]
        if not paths:
            return
        already = [p for p in paths if p in _marked_paths]
        if already and len(already) == len(paths):
            # Everything selected is already marked - unmark it.
            for path in already:
                _marked_paths.remove(path)
            sublime.status_message(
                "SubMerge: unmarked %s (%d marked)"
                % (", ".join(_basename(p) for p in already), len(_marked_paths)))
            return
        if not add:
            del _marked_paths[:]
        for path in paths:
            if path not in _marked_paths:
                _marked_paths.append(path)
        del _marked_paths[:-MAX_PANES]
        sublime.status_message(
            "SubMerge: marked %s"
            % ", ".join(_basename(p) for p in _marked_paths))

    def is_visible(self, add=False, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.exists(p)]
        if not paths or len(paths) > MAX_PANES:
            return False
        marked = all(p in _marked_paths for p in paths)
        if add:
            # The "add" entry doubles as the "remove" entry.
            return marked or (bool(_marked_paths) and
                              len(_marked_paths) + len(paths) <= MAX_PANES)
        return not marked

    def is_enabled(self, add=False, **kwargs):
        return self.is_visible(add=add, **kwargs)

    def description(self, add=False, **kwargs):
        paths = [p for p in _normalize_paths(kwargs) if os.path.exists(p)]
        noun = "Folder" if paths and os.path.isdir(paths[0]) else "File"
        if len(paths) > 1:
            noun += "s"
        if paths and all(p in _marked_paths for p in paths):
            return "SubMerge: Remove %s from Comparison" % noun
        if add:
            return "SubMerge: Add %s to Comparison" % noun
        return "SubMerge: Mark %s for Comparison" % noun


class SubmergeCompareWithMarkedPathCommand(sublime_plugin.WindowCommand):
    """Side bar: compare the selection with whatever was marked earlier."""

    def run(self, **kwargs):
        combined = self._combined(kwargs)
        if len(combined) < 2:
            sublime.error_message(
                "SubMerge: mark a file or folder first "
                "(SubMerge: Mark for Comparison).")
            return

        files = [p for p in combined if os.path.isfile(p)]
        dirs = [p for p in combined if os.path.isdir(p)]

        # Only discard the marks once we know we can act on them: otherwise a
        # mixed selection wipes them and the "mark files only, or folders
        # only" advice cannot be followed without starting over.
        if len(files) == len(combined):
            del _marked_paths[:]
            begin_comparison(self.window,
                             _sources_from_paths(self.window, files))
        elif len(dirs) == len(combined):
            del _marked_paths[:]
            window = self.window
            sublime.set_timeout_async(
                lambda: folders.open_folder_compare(
                    window, dirs, _folder_target_window), 0)
        else:
            sublime.error_message(
                "SubMerge: cannot compare a file with a folder.\n\n"
                "Mark either files only, or folders only.")

    def _combined(self, kwargs):
        combined = [p for p in _marked_paths if os.path.exists(p)]
        for path in _normalize_paths(kwargs):
            if os.path.exists(path) and path not in combined:
                combined.append(path)
        return combined[:MAX_PANES]

    def is_visible(self, **kwargs):
        return bool([p for p in _marked_paths if os.path.exists(p)])

    def is_enabled(self, **kwargs):
        return len(self._combined(kwargs)) >= 2

    def description(self, **kwargs):
        marked = [p for p in _marked_paths if os.path.exists(p)]
        if len(marked) == 1:
            return "SubMerge: Compare with '%s'" % (
                os.path.basename(marked[0].rstrip(os.sep)) or marked[0])
        if len(marked) > 1:
            return "SubMerge: Compare with %d Marked Items" % len(marked)
        return "SubMerge: Compare with Marked"


def _basename(path):
    return os.path.basename(path.rstrip(os.sep)) or path


def _marked_summary():
    """Everything currently marked, as display names."""
    names = [_describe(view) for view in _marked_views()]
    names.extend(_basename(p) for p in _marked_paths if os.path.exists(p))
    return names


class SubmergeClearMarksCommand(sublime_plugin.WindowCommand):
    """Forget every marked tab, file and folder."""

    def run(self):
        names = _marked_summary()
        del _marked[:]
        del _marked_paths[:]
        sublime.status_message(
            "SubMerge: cleared %d mark(s)%s"
            % (len(names), (" - " + ", ".join(names)) if names else ""))

    def is_visible(self):
        return bool(_marked_summary())

    def is_enabled(self):
        return self.is_visible()

    def description(self):
        count = len(_marked_summary())
        if count == 1:
            return "SubMerge: Clear Mark"
        return "SubMerge: Clear %d Marks" % count


class SubmergeCompareOpenTabsCommand(sublime_plugin.WindowCommand):
    """Pick 2 or 3 open tabs from a quick panel."""

    def run(self):
        self.views = [v for v in self.window.views()
                      if not folders.is_folder_view(v)
                      and not v.settings().get("submerge_metadata_view")]
        if len(self.views) < 2:
            sublime.error_message("SubMerge: open at least two tabs first.")
            return
        self.chosen = []
        self._pick()

    def _items(self):
        items = []
        for view in self.views:
            if view.id() in self.chosen:
                continue
            path = view.file_name() or ""
            items.append([_describe(view), path or "(unsaved buffer)"])
        return items

    def _pick(self):
        if len(self.chosen) >= MAX_PANES:
            return self._start()
        items = self._items()
        if not items:
            return self._start()
        prefix = ["Left", "Right", "Third"][min(len(self.chosen), 2)]
        if len(self.chosen) >= 2:
            items = [["\u2014 Compare now \u2014",
                      "Compare the %d selected tabs" % len(self.chosen)]] + items
        self.window.show_quick_panel(
            items, self._on_done, 0, 0,
            placeholder="SubMerge: choose the %s pane" % prefix)

    def _on_done(self, choice):
        if choice < 0:
            return
        if len(self.chosen) >= 2:
            if choice == 0:
                return self._start()
            choice -= 1
        available = [v for v in self.views if v.id() not in self.chosen]
        self.chosen.append(available[choice].id())
        sublime.set_timeout(self._pick, 10)

    def _start(self):
        views = [sublime.View(i) for i in self.chosen]
        views = [v for v in views if v.is_valid()]
        if len(views) < 2:
            return
        begin_comparison(self.window, [Source(view=v) for v in views])

    def is_enabled(self):
        return len(self.window.views()) >= 2


class SubmergeCompareWithFileCommand(sublime_plugin.WindowCommand):
    """Compare the active tab against one or two files chosen from disk."""

    def run(self, group=-1, index=-1):
        view = _view_at(self.window, group, index)
        if view is None:
            return
        self.base = view
        folder = os.path.dirname(view.file_name() or "") or None
        if not hasattr(sublime, "open_dialog"):
            sublime.error_message(
                "SubMerge: this Sublime build has no file dialog API.\n"
                "Open the file in a tab and use 'Compare Open Tabs' instead.")
            return
        sublime.open_dialog(self._chosen, directory=folder, multi_select=True)

    def _chosen(self, paths):
        if not paths:
            return
        if isinstance(paths, str):
            paths = [paths]
        sources = [Source(view=self.base)]
        for path in paths[:MAX_PANES - 1]:
            sources.append(Source(path=path,
                                  view=self.window.find_open_file(path)))
        begin_comparison(self.window, sources)


# ---------------------------------------------------------------------------
# navigation / merging
# ---------------------------------------------------------------------------

class _SessionTextCommand(sublime_plugin.TextCommand):
    def session(self):
        return sessions.session_for_view(self.view)

    def is_enabled(self, **kwargs):
        return self.session() is not None

    def is_visible(self, **kwargs):
        return self.session() is not None


class SubmergeNextDifferenceCommand(_SessionTextCommand):
    def run(self, edit):
        session = self.session()
        if session:
            session.next_hunk(self.view)


class SubmergePreviousDifferenceCommand(_SessionTextCommand):
    def run(self, edit):
        session = self.session()
        if session:
            session.prev_hunk(self.view)


class SubmergeFirstDifferenceCommand(_SessionTextCommand):
    def run(self, edit):
        session = self.session()
        if session:
            session.goto_hunk(0, self.view)


class SubmergeLastDifferenceCommand(_SessionTextCommand):
    def run(self, edit):
        session = self.session()
        if session:
            session.goto_hunk(len(session.hunks()) - 1, self.view)


class SubmergeGotoMovedPartnerCommand(_SessionTextCommand):
    """Jump to where the moved line under the cursor came from."""

    def run(self, edit):
        session = self.session()
        pane = session.pane_of(self.view) if session else None
        if pane is None or not len(self.view.sel()):
            return
        line = self.view.rowcol(self.view.sel()[0].begin())[0]
        moved = getattr(session.alignment, "moved", None)
        partner = moved[pane].get(line) if moved else None
        if partner is None:
            sublime.status_message("SubMerge: this line was not detected as moved")
            return
        other_pane, other_line = partner
        other = session.views[other_pane]
        point = other.text_point(other_line, 0)
        other.sel().clear()
        other.sel().add(sublime.Region(point, point))
        other.show_at_center(point)
        session.window.focus_view(other)
        sublime.status_message("SubMerge: moved line - pane %s line %d"
                               % (PANE_LETTERS[other_pane], other_line + 1))


class SubmergeCopyDifferenceCommand(_SessionTextCommand):
    """Copy the difference under the cursor into another pane.

    `to` may be "left", "right", "ask", or a zero based pane index.
    """

    def run(self, edit, to="right", all_differences=False):
        session = self.session()
        if session is None:
            return
        source = session.pane_of(self.view)
        if source is None:
            return
        target = self._resolve_target(session, source, to)
        if target is None:
            return self._ask(session, source, all_differences)
        self._apply(session, source, target, all_differences)

    def _resolve_target(self, session, source, to):
        if isinstance(to, int):
            return to if 0 <= to < session.pane_count and to != source else None
        if to == "right":
            candidates = list(range(source + 1, session.pane_count))
        elif to == "left":
            candidates = list(range(source - 1, -1, -1))
        else:
            candidates = []
        return candidates[0] if candidates else None

    def _ask(self, session, source, all_differences):
        options = [p for p in range(session.pane_count) if p != source]
        if len(options) == 1:
            return self._apply(session, source, options[0], all_differences)
        items = ["Pane %s \u2014 %s" % (PANE_LETTERS[p], _describe(session.views[p]))
                 for p in options]

        def done(choice):
            if choice >= 0:
                self._apply(session, source, options[choice], all_differences)

        self.view.window().show_quick_panel(
            items, done, 0, 0, placeholder="SubMerge: copy to which pane?")

    def _apply(self, session, source, target, all_differences):
        if all_differences:
            if setting("confirm_copy_all", True):
                if not sublime.ok_cancel_dialog(
                        "SubMerge: copy every difference from pane %s to pane %s?"
                        % (PANE_LETTERS[source], PANE_LETTERS[target]), "Copy All"):
                    return
            session.copy_all(source, target)
            return
        hunk = session.hunk_under_cursor(self.view)
        if hunk is None:
            sublime.status_message("SubMerge: no difference at the cursor")
            return
        index = hunk.index
        if session.copy_hunk(hunk, source, target):
            session.current_hunk = min(index, max(0, len(session.hunks()) - 1))
            session.highlight_current_hunk(scroll=False)
            sublime.status_message("SubMerge: copied difference to pane %s"
                                   % PANE_LETTERS[target])


class SubmergeCopyAllDifferencesCommand(_SessionTextCommand):
    def run(self, edit, to="right"):
        self.view.run_command("submerge_copy_difference",
                              {"to": to, "all_differences": True})


class SubmergeApplyPatchCommand(sublime_plugin.TextCommand):
    """Internal: replace/insert/delete a line range.

    Sublime registers every TextCommand globally, so "internal" in a docstring
    is not a guard - the console, a stray key binding or another package can
    all reach this and destroy a buffer.  is_visible() keeps it out of the
    command palette and run() refuses to touch a view that is not part of a
    live comparison.
    """

    def is_visible(self):
        return False

    def run(self, edit, start_line=0, end_line=0, text="", insert=False,
            delete=False):
        view = self.view
        if sessions.session_for_view(view) is None:
            return
        start_line = max(0, int(start_line))
        end_line = max(start_line, int(end_line))
        last_row = view.rowcol(view.size())[0]

        if delete:
            if start_line > last_row:
                return
            start = view.text_point(start_line, 0)
            end_row = min(end_line - 1, last_row)
            end = view.full_line(view.text_point(end_row, 0)).b
            region = sublime.Region(start, end)
            if end > view.size() - 1 and start > 0 and view.substr(start - 1) == "\n":
                region = sublime.Region(start - 1, view.size())
            view.erase(edit, region)
            return

        if insert:
            if start_line > last_row:
                point = view.size()
                view.insert(edit, point, ("\n" if view.size() else "") + text)
            else:
                point = view.text_point(start_line, 0)
                view.insert(edit, point, text + "\n")
            return

        start = view.text_point(start_line, 0)
        end_row = min(end_line - 1, last_row)
        end_region = view.full_line(view.text_point(end_row, 0))
        ends_with_newline = end_region.b <= view.size() and \
            view.substr(sublime.Region(end_region.b - 1, end_region.b)) == "\n"
        replacement = text + ("\n" if ends_with_newline else "")
        view.replace(edit, sublime.Region(start, end_region.b), replacement)


class SubmergeReplaceAllCommand(sublime_plugin.TextCommand):
    """Internal: used to populate generated views.

    Only ever runs against a view SubMerge itself created and flagged, so that
    invoking it by hand cannot wipe out a real file's buffer.
    """

    def is_visible(self):
        return False

    def run(self, edit, text=""):
        if not self.view.settings().get("submerge_generated"):
            return
        read_only = self.view.is_read_only()
        if read_only:
            self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        if read_only:
            self.view.set_read_only(True)


# ---------------------------------------------------------------------------
# session management commands
# ---------------------------------------------------------------------------

class SubmergeRefreshCommand(sublime_plugin.WindowCommand):
    def run(self):
        session = sessions.get_session(self.window)
        if session:
            session.refresh()
            stats = session.alignment.stats()
            sublime.status_message(
                "SubMerge: %d difference(s), %d moved line pair(s)"
                % (stats["hunks"], stats.get("moved", 0)))
        else:
            view = self.window.active_view()
            if folders.is_folder_view(view):
                folders.rescan(view)

    def is_enabled(self):
        view = self.window.active_view()
        return (sessions.get_session(self.window) is not None
                or folders.is_folder_view(view))


class SubmergeEndComparisonCommand(sublime_plugin.WindowCommand):
    def run(self):
        if sessions.end_session(self.window):
            sublime.status_message("SubMerge: comparison closed")

    def is_enabled(self):
        return sessions.get_session(self.window) is not None


class SubmergeMetadataReportCommand(sublime_plugin.WindowCommand):
    """Show the metadata comparison for the active comparison, the marked
    tabs, or the row selected in a folder comparison."""

    def run(self):
        paths = self._paths()
        if len(paths) < 2:
            sublime.error_message(
                "SubMerge: no comparison to report on.\n\n"
                "Start a comparison, or select a row in a folder comparison.")
            return
        sources = [Source(path=p) for p in paths]
        texts = [s.text() for s in sources]
        identical = (all(t is not None for t in texts)
                     and not core.compare_texts(
                         texts, sessions.options_from_settings()).hunks)
        _open_metadata_report(self.window, sources, content_identical=identical)

    def _paths(self):
        session = sessions.get_session(self.window)
        if session and all(session.sources):
            return list(session.sources)
        view = self.window.active_view()
        if folders.is_folder_view(view) and len(view.sel()):
            row = view.rowcol(view.sel()[0].begin())[0]
            node = folders.entry_for_row(view, row)
            if node and not node.is_dir:
                return [p for p in node.paths if p]
        return [v.file_name() for v in _marked_views() if v.file_name()]

    def is_enabled(self):
        return len(self._paths()) >= 2


def _apply_option_change(window, option):
    """Re-run whatever the setting that just changed actually affects.

    A folder rescan re-stats, re-reads and re-hashes every file in every root,
    so it has to be reserved for settings that change what a scan *produces*.
    Previously any option change refreshed a focused folder result, which
    meant picking a new color preset re-hashed the whole tree.
    """
    session = sessions.get_session(window)
    if session:
        session.refresh()
    view = window.active_view()
    if option in folders.RESCAN_ON and folders.is_folder_view(view):
        folders.rescan(view)


class SubmergeToggleOptionCommand(sublime_plugin.WindowCommand):
    """Toggle a boolean setting and re-run the active comparison."""

    LABELS = {
        "ignore_whitespace": "Ignore Leading/Trailing Whitespace",
        "ignore_all_whitespace": "Ignore All Whitespace",
        "ignore_case": "Ignore Case",
        "ignore_blank_lines": "Ignore Blank Lines",
        "ignore_line_endings": "Ignore End-of-Line Differences (CRLF vs LF)",
        "detect_moved_lines": "Detect Moved Lines",
        "sync_scroll": "Synchronized Scrolling",
        "show_gaps": "Show Alignment Gaps",
        "live_diff": "Live Re-Diff While Typing",
        "compare_metadata": "Compare File Metadata",
        "csv_table_view": "Show CSV/TSV Files as Tables",
        "compare_in_new_window": "Open Comparisons in a New Window",
        "folder_show_identical": "Folder Compare: Show Identical Files",
        "graduated_inline_highlight": "Graduated Inline Highlight Intensity",
    }

    def run(self, option):
        store = settings()
        store.set(option, not store.get(option, False))
        sublime.save_settings(SETTINGS_FILE)
        _apply_option_change(self.window, option)

    def is_checked(self, option):
        return bool(setting(option, False))

    def description(self, option):
        return self.LABELS.get(option, option)


class SubmergeSetOptionCommand(sublime_plugin.WindowCommand):
    """Pick one value for a multi-choice setting (color_preset,
    highlight_style, ...) and re-run the active comparison. Menu items using
    this share one command instead of needing one class per setting."""

    def run(self, option, value):
        store = settings()
        store.set(option, value)
        sublime.save_settings(SETTINGS_FILE)
        sessions.write_color_scheme(force=True)
        _apply_option_change(self.window, option)
        sublime.status_message("SubMerge: %s set to %s" % (option, value))

    def is_checked(self, option, value):
        return setting(option, None) == value


class SubmergeOpenSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.run_command("edit_settings", {
            "base_file": "${packages}/%s/SubMerge.sublime-settings" % PACKAGE,
            "default": ("// Settings in here override those in "
                        "\"SubMerge.sublime-settings\"\n\n{\n\t$0\n}\n"),
        })


class SubmergeOpenKeymapCommand(sublime_plugin.WindowCommand):
    def run(self):
        platform = {"windows": "Default (Windows).sublime-keymap",
                    "osx": "Default (OSX).sublime-keymap",
                    "linux": "Default (Linux).sublime-keymap"}[sublime.platform()]
        self.window.run_command("edit_settings", {
            "base_file": "${packages}/%s/%s" % (PACKAGE, platform),
            "user_file": "${packages}/User/" + platform,
            "default": "[\n\t$0\n]\n",
        })


class SubmergeOpenUserGuideCommand(sublime_plugin.WindowCommand):
    """Render the packaged README into styled HTML and open it in the default
    web browser. Sublime has no built-in Markdown preview, and depending on a
    third-party package for one would be fragile, so the guide is converted
    here and written to a temporary file the browser can reach (the packaged
    copy lives inside the .sublime-package archive and has no real path)."""

    def run(self):
        try:
            source = sublime.load_resource(
                "Packages/%s/README.md" % PACKAGE)
        except Exception as exc:
            sublime.error_message(
                "SubMerge: could not read the user guide.\n\n%s" % exc)
            return

        try:
            page = docs.build_page(source, version=PLUGIN_VERSION)
            # One stable filename, rewritten each time: NamedTemporaryFile
            # with delete=False left a new copy of the guide behind on every
            # invocation, and nothing ever cleaned them up.
            path = os.path.join(tempfile.gettempdir(), GUIDE_FILENAME)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(page)
            # pathname2url rather than "file://" + path: on Windows the
            # latter produces file://C:\... , where the drive letter parses
            # as a hostname and the backslashes are not separators.  This
            # spelling (rather than pathlib.Path.as_uri()) keeps the module
            # importable on Sublime's legacy 3.3 plugin host, so a package
            # built without .python-version degrades instead of failing to
            # load every command.
            url = urllib.parse.urljoin(
                "file:", urllib.request.pathname2url(path))
            webbrowser.open(url)
            sublime.status_message("SubMerge: user guide opened in your browser")
        except Exception as exc:
            sublime.error_message(
                "SubMerge: could not open the user guide in a browser.\n\n%s\n\n"
                "Use 'User Guide (Plain Text)' instead." % exc)


class SubmergeOpenReadmeCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.run_command(
            "open_file", {"file": "${packages}/%s/README.md" % PACKAGE})


# ---------------------------------------------------------------------------
# folder view commands
# ---------------------------------------------------------------------------

class SubmergeFolderOpenRowCommand(sublime_plugin.TextCommand):
    """Enter / double-click inside a folder comparison result."""

    def run(self, edit):
        view = self.view
        window = view.window()
        if not len(view.sel()):
            return
        row = view.rowcol(view.sel()[0].begin())[0]
        node = folders.entry_for_row(view, row)
        if node is None:
            return
        existing = [p for p in node.paths if p]

        if node.is_dir:
            if len(existing) >= 2:
                sublime.set_timeout_async(
                    lambda: folders.open_folder_compare(
                        window, existing, _folder_target_window), 0)
            elif existing:
                window.run_command("open_dir", {"dir": existing[0]})
            return

        if len(existing) < 2:
            if existing:
                window.open_file(existing[0])
            return

        if node.status == folders.STATUS_METADATA:
            _open_metadata_report(window,
                                  [Source(path=p) for p in existing[:MAX_PANES]],
                                  content_identical=True)
            return

        begin_comparison(window, [Source(path=p) for p in existing[:MAX_PANES]])

    def is_enabled(self):
        return folders.is_folder_view(self.view)

    def is_visible(self):
        return self.is_enabled()


class SubmergeFolderRescanCommand(sublime_plugin.WindowCommand):
    """Reload the compared folders (what F5 does inside the results tab)."""

    def run(self, group=-1, index=-1):
        view = _folder_view(self.window, group, index)
        if view is not None:
            folders.rescan(view)

    def is_enabled(self, group=-1, index=-1):
        return _folder_view(self.window, group, index) is not None

    def is_visible(self, group=-1, index=-1):
        return self.is_enabled(group, index)


class SubmergeFolderToggleIdenticalCommand(sublime_plugin.WindowCommand):
    """Show/hide identical files in a folder comparison result."""

    def run(self, group=-1, index=-1):
        store = settings()
        store.set("folder_show_identical",
                  not store.get("folder_show_identical", True))
        sublime.save_settings(SETTINGS_FILE)
        view = _folder_view(self.window, group, index)
        if view is not None:
            folders.rescan(view)

    def is_checked(self, group=-1, index=-1):
        return bool(setting("folder_show_identical", True))

    def is_enabled(self, group=-1, index=-1):
        return _folder_view(self.window, group, index) is not None

    def is_visible(self, group=-1, index=-1):
        return self.is_enabled(group, index)


# ---------------------------------------------------------------------------
# listeners
# ---------------------------------------------------------------------------

class SubmergeListener(sublime_plugin.EventListener):

    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "submerge_active":
            value = sessions.session_for_view(view) is not None
        elif key == "submerge_folder_view":
            value = folders.is_folder_view(view)
        elif key == "submerge_has_marked":
            value = bool(_marked_summary())
        else:
            return None
        if operator == sublime.OP_EQUAL:
            return value == bool(operand)
        if operator == sublime.OP_NOT_EQUAL:
            return value != bool(operand)
        return None

    def on_modified_async(self, view):
        session = sessions.session_for_view(view)
        if session is None or not setting("live_diff", True):
            return
        global _pending_refresh
        _pending_refresh += 1
        token = _pending_refresh
        delay = int(setting("live_diff_delay_ms", 400) or 400)

        def maybe_refresh():
            # Only the newest keystroke in a burst gets to re-diff, and the
            # diff itself runs off the UI thread - on a large file it takes
            # long enough to be felt as the editor stalling.
            if token == _pending_refresh and session.is_alive():
                session.refresh_async()

        sublime.set_timeout(maybe_refresh, delay)

    def on_post_save_async(self, view):
        session = sessions.session_for_view(view)
        if session:
            session.refresh()

    def on_close(self, view):
        folders.forget(view.id())
        session = sessions.session_for_view(view)
        if session and not session.is_alive():
            sessions.end_session(
                session.window,
                restore_layout=bool(setting("restore_layout_on_close", True)))

    def on_text_command(self, view, command_name, args):
        if command_name == "drag_select" and (args or {}).get("by") == "words":
            if folders.is_folder_view(view):
                # double click inside a folder result opens the comparison
                sublime.set_timeout(
                    lambda: view.run_command("submerge_folder_open_row"), 30)
        return None
