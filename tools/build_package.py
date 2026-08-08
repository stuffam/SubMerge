#!/usr/bin/env python3
"""
Build SubMerge.sublime-package.

A .sublime-package is a plain zip whose *root* is the package directory - so
"SubMerge.py" sits at the top of the archive, not "SubMerge/SubMerge.py".
Sublime reads files straight out of it, which is why the archive has to carry
everything the plugin loads at runtime, README.md included: the user guide
command reads it back with sublime.load_resource().

Contents are chosen by an explicit include list rather than by excluding
things.  A missed exclusion ships somebody's .sublime-workspace or a stray
credential file to every user; a missed inclusion just fails the manifest
check below.

    python3 tools/build_package.py [--output-dir dist]
"""

import argparse
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_NAME = "SubMerge.sublime-package"

# Everything the installed plugin needs, relative to the repo root.
INCLUDE_FILES = [
    "SubMerge.py",
    "SubMerge.sublime-settings",
    "SubMergeFolder.sublime-syntax",
    "SubMergeMetadata.sublime-syntax",
    "Main.sublime-menu",
    "Context.sublime-menu",
    "Side Bar.sublime-menu",
    "Tab Context.sublime-menu",
    "Default (Linux).sublime-keymap",
    "Default (OSX).sublime-keymap",
    "Default (Windows).sublime-keymap",
    "messages.json",
    # Loaded at runtime by SubmergeOpenUserGuideCommand / OpenReadmeCommand.
    "README.md",
]

INCLUDE_TREES = [
    ("modules", ".py"),
    ("messages", ".txt"),
]

# Without these the plugin does not work at all, so a build that somehow
# produced an archive missing one of them is a failed build, not a warning.
REQUIRED_IN_ARCHIVE = [
    "SubMerge.py",
    "modules/__init__.py",
    "modules/submerge_core.py",
    "modules/submerge_session.py",
    "modules/submerge_folder.py",
    "modules/submerge_metadata.py",
    "modules/submerge_table.py",
    "modules/submerge_docs.py",
    "SubMerge.sublime-settings",
    "README.md",
]

# Nothing matching these may ever end up in a distributed archive.
FORBIDDEN_SUFFIXES = (
    ".pyc", ".sublime-workspace", ".sublime-project", ".DS_Store",
)


def collect():
    """Return [(absolute source path, archive name)], sorted."""
    entries = []
    for name in INCLUDE_FILES:
        path = os.path.join(REPO, name)
        if not os.path.isfile(path):
            raise SystemExit("build: missing required file %r" % name)
        entries.append((path, name))

    for directory, suffix in INCLUDE_TREES:
        root = os.path.join(REPO, directory)
        if not os.path.isdir(root):
            raise SystemExit("build: missing required directory %r" % directory)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in sorted(filenames):
                if not filename.endswith(suffix):
                    continue
                path = os.path.join(dirpath, filename)
                archive = os.path.relpath(path, REPO).replace(os.sep, "/")
                entries.append((path, archive))

    return sorted(set(entries), key=lambda pair: pair[1])


def build(output_dir):
    entries = collect()
    names = [archive for _path, archive in entries]

    for archive in names:
        if archive.endswith(FORBIDDEN_SUFFIXES):
            raise SystemExit("build: refusing to ship %r" % archive)

    missing = [name for name in REQUIRED_IN_ARCHIVE if name not in names]
    if missing:
        raise SystemExit("build: archive would be missing %s"
                         % ", ".join(missing))

    os.makedirs(output_dir, exist_ok=True)
    target = os.path.join(output_dir, PACKAGE_NAME)
    # Deterministic: fixed timestamp and ordered entries, so rebuilding the
    # same source produces a byte-identical archive.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as handle:
                archive.writestr(info, handle.read())

    with zipfile.ZipFile(target) as archive:
        broken = archive.testzip()
        if broken is not None:
            raise SystemExit("build: corrupt entry %r" % broken)
        count = len(archive.namelist())

    size = os.path.getsize(target)
    print("%s  (%d files, %.1f KiB)" % (target, count, size / 1024.0))
    for name in names:
        print("  %s" % name)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=os.path.join(REPO, "dist"))
    args = parser.parse_args(argv)
    build(args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
