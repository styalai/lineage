# 🧬 Lineage

Track the lineage of your experiments as a **graph of snapshots and diffs**, without interfering with Git.

> **Status:** v0.1 — commands: `add`, `diff`, `revert`, `remove`, `note`, `log`, `web`, `init`.
> Coming soon: `list`, `show`, `graph`, `gc`, `run`, shell autocompletion.

## Demo

<video src="https://raw.githubusercontent.com/styalai/lineage/main/assets/demo.mp4" controls width="100%"></video>

Can't see the video above? [Watch `demo.mp4`](assets/demo.mp4) directly.

---

## Requirements

- **Python 3.11+** (no third-party runtime dependencies)
- macOS, Linux, or Windows

## Install

### One-line install (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/install.sh | bash
```

This installs lineage to `~/.lineage/<version>/` and writes a launcher to
`~/.local/bin/lineage`. The installer also adds `~/.local/bin` to your PATH
in `~/.zshrc` / `~/.bashrc` if it isn't already there. **Open a new shell**
after install so the PATH change takes effect.

```bash
lineage --help
```

To pin a specific version:

```bash
LINEAGE_VERSION=v0.1.0 curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/install.sh | bash
```

To install from a local tarball (e.g. for testing):

```bash
bash install.sh /path/to/lineage-0.1.0.tar.gz
```

### One-line install (Windows, PowerShell)

```powershell
irm https://raw.githubusercontent.com/styalai/lineage/main/install.ps1 | iex
```

Installs to `%USERPROFILE%\.lineage\<version>\` and adds
`%USERPROFILE%\.local\bin` to your user PATH. **Open a new PowerShell window**
to pick up the PATH change.

### Install from this repo (dev)

If you're hacking on lineage itself, add `bin/` to your `PATH`:

```bash
# macOS / Linux
export PATH="$PATH:/Users/arthur/Documents/code/lineage/bin"

# Windows (PowerShell)
$env:Path += ";C:\path\to\lineage\bin"
```

Or invoke directly:

```bash
python3.11 -m lineage --help
```

An optional `pip install -e .` (inside a venv) also installs a `lineage`
entry point system-wide.

### Uninstall

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/styalai/lineage/main/uninstall.sh | bash
# or: bash uninstall.sh

# Windows
irm https://raw.githubusercontent.com/styalai/lineage/main/uninstall.ps1 | iex
```

Removes `~/.lineage/` and the launcher at `~/.local/bin/lineage`.

### Configuration

The installer respects these environment variables (all optional):

| Variable | Default | Notes |
|---|---|---|
| `LINEAGE_REPO` | `styalai/lineage` | GitHub `<owner>/<repo>` to fetch from. |
| `LINEAGE_VERSION` | `latest` | `vX.Y.Z` to pin a specific release. |
| `LINEAGE_HOME` | `~/.lineage` | Where the source tree is installed. |
| `LINEAGE_BIN_DIR` | `~/.local/bin` | Where the `lineage` launcher is written. |

---

## Using lineage

The core loop is **checkpoint → change → checkpoint**. Each `add` freezes
your current workspace files as a new experiment node; `diff` compares nodes,
`log` records numbers on them, and `revert` restores files from any node.
The first `add` in a directory creates `.lineage/` and adds it to
`.gitignore` — your project files are never touched.

### A typical session

```bash
cd your-project

lineage add -m "baseline"              # b0: first experiment, always a snapshot
lineage log b0 val_loss=3.14           # attach a log to it
# ... edit code, run training ...
lineage add -m "lr 3e-4" --from b0     # create a child experiment id->b0a
lineage log b0a loss=2.91 acc=0.81     # record metrics (values are strings)

lineage diff b0 b0a                    # what changed between the two
lineage diff b0a --stat                # or: only change stats

lineage revert b0 --dry-run            # preview restoring b0a ...
lineage revert b0                      # ... then actually restore it
lineage web                            # inspect/manage the graph in a browser
```

### Floating baselines vs attached children

- A bare `add` creates a **floating** baseline: the next `bN` number (`b1`,
  `b2`, …), always a full snapshot, with no parent edge. Use these for
  independent starting points.
- `add --from <id>` creates an **attached** child: a path-encoded id
  (`b0a` under `b0`, `b0aa` under `b0a`, …), stored as a diff against the
  parent by default (pass `--snapshot` for a full copy instead).
- **Snapshots hold everything; diffs hold only what changed.** If a file
  isn't in a diff, it's identical to the parent — nothing was skipped.
- `revert` overwrites tracked files but never deletes your untracked ones;
  use `--dry-run` first when unsure.

### Moving nodes renames them

There is no `connect` CLI command — moves happen in `lineage web`
(right-click → **Connect to…** then click the new parent, or drag an edge
dot onto another node; right-click → **Unconnect** to detach). A move
renames the node so its id always reflects its position, and the subtree
follows (`b2` under `b0a` becomes `b0ab`; its child becomes `b0aba`, …):

- **Connect** collapses a snapshot into a diff against the new parent
  whenever it round-trips byte-identically (binary content keeps it a
  snapshot).
- **Unconnect** materializes a diff into a standalone snapshot first, then
  renames to a fresh floating `bN`.

After any move, old IDs no longer exist — re-read them from the UI.

### `lineage init`: instructions for coding agents

`init` stamps lineage usage instructions into a project so AI coding agents
(opencode, Claude Code, Codex) checkpoint their own experiments:

```bash
cd your-project
lineage init --for opencode   # writes AGENTS.md
lineage init --for claude     # writes CLAUDE.md
lineage init --for codex      # writes AGENTS.md (Codex reads AGENTS.md too)
lineage init --for all        # writes both files
```

- The content is the `AGENTS.md` shipped with lineage — the full workflow
  above, condensed for agents.
- `init` never overwrites an existing file unless you pass `--force`;
  re-running when the content already matches reports "already up to date".
- It respects the global `-C DIRECTORY` flag, so you can stamp another
  project without `cd`-ing: `lineage -C ~/my-project init --for all`.

---

## Commands

| Command | Description |
|---|---|
| `lineage add [-m MSG] [--from ID] [--snapshot] [--detached]` | Snapshot the workspace as a floating baseline, or attach under `--from`. |
| `lineage diff A [B] [--stat] [--files]` | Show unified diff between two experiments (or A and its parent). |
| `lineage revert ID [--dry-run]` | Restore workspace to a given experiment. |
| `lineage remove ID [--recursive] [--force]` | Delete an experiment. |
| `lineage note ID [--append]` | Edit (or append to) an experiment's notes. |
| `lineage log ID key=value ...` | Record metrics on an experiment (any key, string values). |
| `lineage init [--for opencode\|claude\|codex\|all] [--force]` | Write agent instruction files (`AGENTS.md` / `CLAUDE.md`) into the project. |
| `lineage web [--port N] [--no-browser] [--metric-a K] [--metric-b K]` | Launch the local graph UI in your browser. |

Run `lineage <command> --help` for options.

The web UI can also manage the graph directly: right-click the canvas for a
**New experiment** (floating baseline), right-click a node for **New child**,
**Log**, **Diff vs parent**, **Connect to…**, **Focus**, **Unconnect**, and
**Remove**. See "Moving nodes renames them" above for what moves do.

---

## Layout

```
your-project/
  src/
  train.py

  .lineage/
    .gitignore            # auto-managed, contains ".lineage/"
    experiments/
      b0/
        snapshot/         # full copy of workspace at this point
        meta.json
        notes.md
      b0a/
        diff.patch        # unified diff against parent
        meta.json
        notes.md
      b1/
        snapshot/         # floating baseline (no parent edge)
        meta.json
        notes.md
```

`.lineage/` is **isolated from your project**: deleting it has zero effect on your files.
It is also auto-added to your `.gitignore` (created if missing) on first run.

---

## How it works

- **IDs** reflect position. Floating experiments are numbered `b0` (root),
  `b1`, `b2`, … in creation order. Attaching a node under a parent renames
  it (plus its subtree) to a path id — parent plus a letter: `b0a`, `b2a`,
  `b0aa`, … Detaching renames back to a fresh `bN`.
- **Snapshots** are real byte copies of your workspace files. We deliberately
  do not use hardlinks: a hardlinked snapshot would silently track later
  in-place modifications to the original file, which would corrupt your
  experiment history. The hardlink / copy-on-write optimization from the spec
  can be enabled later behind a config flag.
- **Diffs** are pure-Python unified diffs (no `diff`/`patch` binaries) so the tool behaves
  identically on macOS, Linux, and Windows.
- **Reconstruction** finds the nearest snapshot ancestor, copies it, then applies diffs in
  order up to the target experiment.

---

## Workspace rules

- Includes **staged, unstaged, and untracked** files.
- Always reads from your **current files** — never from git.
- Excludes `.lineage/`, `.git/`, `__pycache__/`, `*.pyc`, `node_modules/`, `.DS_Store`.
- Does **not** read `.gitignore` (so you can keep the same set even if you change git
  ignores). This is a deliberate choice to avoid silently dropping files.

---

## Limitations (v0.1)

- No binary file diffs (text only).
- Single-user, single-CWD at a time (no concurrent `lineage add` in parallel).
- No automatic checkpointing (always a diff after the first snapshot; a snapshot is forced
  every 10 diffs in a chain).
- `list`, `show`, `graph`, `gc`, `run` are not implemented yet.

