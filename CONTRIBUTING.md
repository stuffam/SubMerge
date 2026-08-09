# Working on SubMerge

Everything below runs on a plain Python 3 install. There is nothing to
`pip install` except the linter, and no need for Sublime Text.

## Tests

```bash
python3 -m unittest discover -s test -v
```

`submerge_core`, `submerge_docs`, `submerge_metadata` and `submerge_table`
import nothing from Sublime and are tested directly. `submerge_session` and
`submerge_folder` do, so `test/test_submerge.py` installs a small stand-in for
the `sublime` module before importing them — enough to reach the folder
scanning, gap markup and color validation without the editor.

`SubMerge.py` itself is command wiring and is not unit tested; CI byte-compiles
it on every supported Python version instead.

## Lint

```bash
python3 -m pip install pycodestyle
pycodestyle SubMerge.py modules tools test
```

Line length and exclusions come from `setup.cfg`, so a bare run checks exactly
what CI checks. The fixtures under `test/SubMerge-Test-Data/` are excluded on
purpose: their formatting is the input under test, so a linter must never be
the reason one of them changes. For the same reason `.gitattributes` stops Git
normalizing their line endings.

## Build

```bash
python3 tools/build_package.py
```

Writes `dist/SubMerge.sublime-package`, which is a plain zip whose *root* is
the package directory. The script picks contents from an explicit include list
rather than by excluding things — a missed exclusion ships somebody's
workspace file to every user, whereas a missed inclusion just fails the
manifest check. It also refuses to produce an archive that is missing anything
the plugin loads at runtime, `README.md` included: the user guide command reads
it back with `sublime.load_resource()`.

Builds are deterministic; rebuilding the same source gives a byte-identical
archive, and CI asserts that.

To test a build, drop the file into `Installed Packages/` (Preferences →
Browse Packages…, then up one level) and restart Sublime Text completely.

## What ships, and the two places that decide it

There are two distribution paths, and they choose contents by opposite rules.
A file that needs to reach users has to survive both.

- **The GitHub Release asset** is built by `tools/build_package.py` from the
  allowlist in `INCLUDE_FILES` / `INCLUDE_TREES`. A new runtime file is absent
  until it is added there.
- **Package Control** never runs that script. It installs the GitHub archive of
  the tag, which is `git archive` output and therefore governed by the
  `export-ignore` denylist in `.gitattributes`. A new runtime file ships
  automatically; a new *development* directory ships too, unless it is added to
  that block.

So: adding something the plugin loads means editing `build_package.py`; adding
a directory of tests, tooling or notes means editing `.gitattributes`. Check
what Package Control would actually install with:

```bash
git archive --worktree-attributes --format=tar HEAD | tar -t | sort
```

That list should match the build script's manifest. Nothing enforces this
automatically.

## Cutting a release

A release is published by pushing a `v*` tag, and by nothing else — no branch
push publishes anything.

1. Bump `PLUGIN_VERSION` in `SubMerge.py`.
2. Add `messages/<version>.txt` with the upgrade note, and point at it from
   `messages.json`. Sublime shows this to users after the package updates.
3. Commit, then tag and push:

```bash
git tag v1.1.0 && git push origin v1.1.0
```

CI reruns the full test matrix, lint and build, then attaches
`SubMerge.sublime-package` to a GitHub Release with notes generated from the
commits since the previous tag. It uploads the exact artifact the build job
produced rather than rebuilding, so what ships is what was tested.

Those three version sites drift silently — nothing in Sublime cross-checks
them — so the build refuses to run on a tag unless all three agree:

```bash
python3 tools/build_package.py --expect-version v1.1.0
```

Run that before tagging to check locally. Re-running a tag build refreshes the
attached asset instead of failing.

A tag containing a hyphen (`v1.1.0-rc1`) is published as a prerelease. The
suffix describes the release, not the plugin, so `PLUGIN_VERSION` and
`messages.json` still read `1.1.0` — the check compares against the base
version.

## Module versions

Each module in `modules/` carries a `VERSION` that `REQUIRED_VERSIONS` in
`SubMerge.py` checks at load time. Sublime does not always re-execute
sub-modules when the top-level plugin file reloads, so overwriting the package
in place can leave new code calling into old modules — which mostly fails
silently, since the function names rarely change. **Bump the module's `VERSION`
and the matching entry in `REQUIRED_VERSIONS` whenever you change a module's
public surface**, so that mismatch is reported instead of quietly misbehaving.

## CI

`.github/workflows/ci.yml` runs tests on Python 3.8 (what Sublime Text 4
bundles, and therefore the version that has to pass) plus 3.12, across Linux,
macOS and Windows — the last two because `file://` URL construction, symlink
handling and permission bits all differ there. Lint and build run on Linux
only, and the built package is uploaded as a workflow artifact.
