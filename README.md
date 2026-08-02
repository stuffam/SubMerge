# SubMerge

**Compare files and folders inside Sublime Text.**

SubMerge shows two or three files side by side, highlights exactly what is
different, and lets you copy changes from one file to the other. It also
compares whole folders, so you can see at a glance which files match and which
don't. If you have used WinMerge, Beyond Compare, or the "diff" view in a Git
tool, this will feel familiar.

NOTICE: This plugin was developed with the assistance of [Claude]
(https://www.anthropic.com/claude), Anthropic's AI assistant.

---

## Contents

1. [Installing](#installing)
2. [Your first comparison](#your-first-comparison)
3. [Reading the colors](#reading-the-colors)
4. [Moving between differences](#moving-between-differences)
5. [Copying changes between files](#copying-changes-between-files)
6. [Comparing three files](#comparing-three-files)
7. [Comparing folders](#comparing-folders)
8. [Comparing file details (size, dates, and so on)](#comparing-file-details)
9. [Viewing CSV and spreadsheet files as tables](#viewing-csv-files-as-tables)
10. [Changing what counts as a difference](#changing-what-counts-as-a-difference)
11. [Changing how differences look](#changing-how-differences-look)
12. [Keyboard shortcuts](#keyboard-shortcuts)
13. [Settings](#settings)
14. [Troubleshooting](#troubleshooting)
15. [Things SubMerge cannot do](#things-submerge-cannot-do)

---

## Installing

1. In Sublime Text, open the **Preferences** menu and choose
   **Browse Packages…**. A folder window opens.
2. Go **up one level**, into the folder called `Installed Packages`.
3. Copy `SubMerge.sublime-package` into that folder.
4. **Quit Sublime Text completely and start it again.** Closing the window is
   not enough — on a Mac use **Sublime Text → Quit Sublime Text**, on Windows
   use **File → Exit**.

That's it. You'll find SubMerge under the **Tools** menu, and this guide at
**Tools → SubMerge → User Guide** (it opens in your web browser).

> **If you were given a plain folder instead of a `.sublime-package` file:**
> put the whole `SubMerge` folder inside the `Packages` folder from step 1
> instead, then restart.

---

## Your first comparison

The quickest way, if both files are already open in tabs:

1. Hold **Ctrl** (**Cmd** on a Mac) and click the two tabs you want to compare,
   so both are selected.
2. Right-click either tab and choose **SubMerge: Compare Selected Tabs**.

The window splits into two side-by-side panes and the differences light up.

**Other ways to start a comparison:**

| If your files are… | Do this |
|---|---|
| Visible in the sidebar | Ctrl/Cmd-click both files, right-click, choose **SubMerge: Compare Selected Files** |
| Open in tabs | **Tools → SubMerge → Compare Open Tabs…**, then pick them from the list |
| One open, one on disk | **Tools → SubMerge → Compare Current Tab With File…** |
| Not next to each other | See [Marking files](#marking-files-to-compare-them-later) below |

**If the files turn out to be identical**, SubMerge tells you so and doesn't
open anything — no need to squint at two identical panes wondering if you
missed something.

### Marking files to compare them later

Sometimes the two things you want to compare aren't conveniently next to each
other — different folders, different windows, or you just want to pick them one
at a time. Use marking:

1. Right-click the first file (in the sidebar or its tab) and choose
   **SubMerge: Mark for Comparison**.
2. Right-click the second one and choose **SubMerge: Compare with Marked**.

To un-mark something, right-click it again — the menu will now say
**Remove from Comparison**. To clear everything, choose **Clear Marks**.

---

## Reading the colors

Each *kind* of difference gets its own color:

| Color | What it means |
|---|---|
| **Green** | This file has a line the other one doesn't — something was added here |
| **Yellow** | This line is completely different from the matching line |
| **Orange** | Only part of the line is different — just the changed words are colored |
| **Red** | Same idea, but most of the line changed rather than a word or two |
| **Blue** | This line was moved — it still exists in the other file, just somewhere else |
| **Grey/shaded block** | An empty gap, inserted so matching lines stay side by side |

The exact shades come from your Sublime color scheme, so they'll blend with
whatever theme you use.

**About the gaps:** when one file has extra lines, SubMerge inserts a blank
shaded block in the *other* file so the matching lines stay lined up on screen.
Nothing is added to your actual file — it's purely visual.

**About the minimap:** the small overview bar on the right also shows the
difference colors, so you can spot clusters of changes without scrolling.

---

## Moving between differences

Don't hunt for changes by scrolling — jump between them:

- **F7** — next difference
- **Shift+F7** — previous difference

The status bar at the bottom shows where you are, like `difference 3 of 12`.
Both panes scroll together, so matching lines stay across from each other.

For a moved line (blue), press **Ctrl+Alt+J** (**Cmd+Alt+J** on a Mac) to jump
to where that line ended up in the other file.

---

## Copying changes between files

Put your cursor on a difference, then:

- **Ctrl+Alt+→** — copy this difference to the pane on the **right**
- **Ctrl+Alt+←** — copy this difference to the pane on the **left**

On a Mac, use **Cmd** instead of **Ctrl**.

To copy *every* difference at once, add **Shift**:
**Ctrl+Alt+Shift+→**. You'll be asked to confirm first, since it changes a lot
at once.

All of these are also on the right-click menu under **SubMerge**.

> **Copying changes the file in the other pane, but does not save it.** Look
> for the unsaved-changes dot on the tab, and save normally with Ctrl+S / Cmd+S.
> If you copy something by mistake, **Undo** (Ctrl+Z / Cmd+Z) works normally —
> just make sure the pane you're undoing in is the one that changed.

---

## Comparing three files

Everything above works with three files as well as two. Select three tabs, or
three files in the sidebar, and you get three panes labelled **A**, **B**, and
**C** from left to right.

With three panes, "copy left" and "copy right" move to the neighbouring pane.
To choose a specific destination, right-click and use
**Copy Difference To…**, which asks which pane you mean.

Panes **B** and **C** are both compared against pane **A**, so put your
"original" or "reference" version on the left.

---

## Comparing folders

Select two (or three) folders in the sidebar, right-click, and choose
**SubMerge: Compare Selected Folders**. A results tab opens listing everything
in both folders, including sub-folders:

```
  [=] AB  notes.txt
  [!] AB  report.docx
  [+] A-  old-draft.txt
  [!] AB  images/
```

| Marker | Meaning |
|---|---|
| `[=]` | Identical in both folders |
| `[!]` | Exists in both, but the contents differ |
| `[+]` | Only exists in some of the folders |
| `[~]` | Contents match, but file details differ (see the next section) |

The `AB` column shows which folders contain that item — `A-` means it's in the
first folder only.

**Press Enter** (or double-click) on any row to open it: a file opens a
side-by-side comparison, a folder opens a comparison of that sub-folder.

Useful extras, all on the right-click menu:

- **Show Identical Files** — turn this off to hide everything that matches, so
  only the differences remain.
- **Reload Compared Folders** (or **F5**) — re-check the folders after you've
  changed something.

**If every file matches**, SubMerge just tells you so and doesn't open a
results tab.

---

## Comparing file details

Sometimes two files have identical contents but differ in other ways — one is
newer, or has different permissions, or uses different line endings.

Turn on **Tools → SubMerge → Comparison Options → Compare File Metadata**
(it's off by default, because it slows down folder comparisons on large
folders). Then, when you compare two files whose contents match but whose
details don't,
SubMerge offers to open a **File Metadata Comparison** tab showing:

file name and location, size, modified/created/accessed dates, permissions,
read-only status, line count, line-ending style, whether the file ends with a
blank line, byte order mark, and detected text encoding.

A `!` marks something that differs, `=` something that matches, and `~`
something that differs but is currently being ignored by your settings.

You can open this report any time with **Ctrl+Alt+I** (**Cmd+Alt+I**), or from
**Tools → SubMerge → File Metadata Comparison…**.

With this option on, folder comparisons also use the `[~]` marker for files
whose contents match but whose details don't.

> Note: SubMerge can *show* these differences, but cannot change file dates or
> permissions for you.

---

## Viewing CSV files as tables

Comma- and tab-separated files are hard to compare as raw text, because one
extra comma shifts everything. Turn on **Tools → SubMerge → Comparison
Options → Show CSV/TSV Files as Tables** and SubMerge lays them out in neat
aligned columns first:

```
1 │ id  │ name        │ notes
──┼─────┼─────────────┼──────────────────
2 │ 1   │ Smith, John │ multi
  │     │             │ line note
3 │ 2   │ Ann         │ short
```

Long cells wrap inside their column, and both files use the same column widths
so everything lines up. Quoted fields containing commas or line breaks are
handled properly.

> **Table view is read-only.** You're looking at a tidied-up rendering, not the
> real file, so copying differences is switched off. Turn the option back off
> to compare and edit the files normally.

---

## Changing what counts as a difference

Under **Tools → SubMerge → Comparison Options**, tick any of these to make
SubMerge ignore things you don't care about:

| Option | Use it when |
|---|---|
| **Ignore Leading/Trailing Whitespace** | Indentation changed but the code didn't |
| **Ignore All Whitespace** | Spacing was reformatted throughout |
| **Ignore Case** | `Name` versus `name` doesn't matter to you |
| **Ignore Blank Lines** | Extra empty lines were added or removed |
| **Ignore End-of-Line Differences** | Comparing a Windows file with a Mac/Linux file |
| **Detect Moved Lines** | Highlight moved lines in blue instead of as delete + add |

**The end-of-line one is on by default**, and worth knowing about. Windows and
Mac/Linux mark the end of each line differently. Leaving it on means the same
text saved on different systems compares as identical. Turn it *off* when the
line-ending style is exactly what you're checking.

---

## Changing how differences look

Under **Tools → SubMerge → Highlighting**:

**Highlight Style** changes how differences are drawn:

- **Background Fill** (default) — solid colored highlight, the classic look,
  and the only one that also shows in the minimap
- **Underline** — a colored line underneath; your normal syntax colors stay
  visible
- **Squiggly Underline** — same, with a wavy line like a spell-checker

**Graduated Inline Highlight Intensity** (on by default) — a small typo shows
orange, a heavily rewritten line shows red, so you can tell big changes from
tiny ones at a glance.

**Color Preset** changes the colors used in folder comparisons, metadata
reports, and the gap blocks. (The side-by-side difference colors come from
your Sublime color scheme — see [Things SubMerge cannot
do](#things-submerge-cannot-do).) Presets include **Vivid**, **Classic**,
**High Contrast**, **Pastel**, and **Colorblind Safe**.

---

## Keyboard shortcuts

On a Mac, use **Cmd** wherever the table says **Ctrl**.

| Action | Shortcut |
|---|---|
| Compare the tabs you've selected | Ctrl+Alt+Shift+D |
| Compare open tabs (pick from a list) | Ctrl+Alt+D |
| Compare current tab with a file on disk | Ctrl+Alt+O |
| Mark this tab for comparison | Ctrl+Alt+M |
| Compare with the marked tab | Ctrl+Alt+Shift+M |
| **Next difference** | **F7** |
| **Previous difference** | **Shift+F7** |
| First / last difference | Ctrl+Alt+Home / Ctrl+Alt+End |
| Jump to a moved line's other half | Ctrl+Alt+J |
| **Copy difference right / left** | **Ctrl+Alt+→ / ←** |
| Copy *all* differences right / left | Ctrl+Alt+Shift+→ / ← |
| File metadata comparison | Ctrl+Alt+I |
| Refresh the comparison | Ctrl+Alt+R |
| Close the comparison | Ctrl+Alt+Shift+W |
| Open selected row (folder results) | Enter |
| Reload folders (folder results) | F5 |

To change these: **Tools → SubMerge → Key Bindings**.

---

## Settings

Most things can be set from the menus, but everything is available in the
settings file: **Tools → SubMerge → Settings**. This opens two panes — the
defaults on the left (read-only, with every option explained), and your own
settings on the right. Add only the options you want to change to the right
pane, then save.

A few worth knowing about:

| Setting | What it does |
|---|---|
| `compare_in_new_window` | Opens comparisons in a separate window instead of splitting the current one |
| `live_diff` | Re-checks differences as you type — turn off for very large files |
| `folder_compare_mode` | `content` is exact but slower; `size_and_time` is much faster on big folders |
| `folder_exclude_patterns` | Folders/files to skip, like `.git` and `node_modules` |
| `layout_on_close` | What the window looks like after you close a comparison |

---

## Troubleshooting

**Nothing happens / SubMerge isn't in the Tools menu.**
Quit Sublime Text completely and start it again — not just close the window.

**"Mismatched modules" message, or things behave oddly after an update.**
Same fix: quit completely and restart. Sublime sometimes keeps parts of the
old version loaded when a package is replaced while it's running.

**Every line shows as different.**
The two files probably use different line endings (Windows versus Mac/Linux).
Check that **Tools → SubMerge → Comparison Options → Ignore End-of-Line
Differences** is ticked — it is on by default, so it may have been turned off.

**The panes drift out of alignment as I scroll.**
Check that word wrap is off. SubMerge turns it off automatically in compared
files, but a setting elsewhere may be forcing it back on.

**I can't copy differences.**
Two common reasons: you're in CSV table view (read-only by design — turn the
option off), or the receiving file is read-only.

**It's slow on very large files or folders.**
Turn off `live_diff` and use Ctrl+Alt+R to refresh manually. For folders, set
`folder_compare_mode` to `size_and_time`, and turn off **Compare File
Metadata** if you don't need it.

**The comparison is out of date after I edited a file elsewhere.**
Press **Ctrl+Alt+R** to refresh.

---

## Things SubMerge cannot do

These are limits of what Sublime Text allows a plugin to do, not missing
features:

- **The side-by-side difference colors can't be customized directly.** They
  come from your Sublime color scheme. To change them, change your color
  scheme (**Preferences → Select Color Scheme…**) — each one has its own
  palette. Folder, metadata, and gap colors *can* be customized.
- **Tabs keep their own filenames.** In a comparison, each tab shows its own
  file name rather than a combined "A ↔ B" title. The combined title appears
  in the status bar instead.
- **The two minimaps don't line up with each other**, because the gap blocks
  aren't drawn in the minimap.
- **Underline and squiggly styles don't appear in the minimap** — use
  Background Fill if you want differences visible there.
- **A gap needed above the very first line** appears just below it instead.
- **No lines drawn between the panes** connecting matching sections.
- **Binary files and images can't be compared.** Folder comparison will still
  tell you *whether* they differ.
- **File dates and permissions can be compared but not copied or changed.**
- **Three-way comparison lines files up against pane A**; it isn't a Git-style
  merge with a common ancestor, and there's no automatic conflict resolution.
- **Menu entries can't appear above Sublime's own** right-click items.
- **Scrolling sync is checked many times a second rather than instantly**, so
  a very fast flick-scroll can briefly lag in the other pane.

---

## Getting help

Report problems or ask questions wherever you obtained SubMerge. If you're
reporting a bug, it helps to include your Sublime Text build number
(**Help → About Sublime Text**), your operating system, and anything shown in
the console (**View → Show Console**).

---

## Acknowledgments

SubMerge was developed through an extensive collaborative process with
[Claude], Anthropic's AI assistant, which helped design, debug across platforms,
and refine the plugin's features and settings through repeated rounds of
real-world testing and feedback.