# 🧬 Lineage

Track the lineage of your experiments as a **graph of snapshots and diffs**, without interfering with Git.

> **Status:** v0.1 — commands: `add`, `diff`, `revert`, `remove`, `note`, `log`, `web`.
> Coming soon: `list`, `show`, `graph`, `gc`, `run`.

---

## Requirements

- **Python 3.11+** (no third-party runtime dependencies)
- macOS, Linux, or Windows
- No `pip install` required

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

## Quick start

```bash
cd your-project

lineage add -m "baseline"           # creates b0 as a snapshot
lineage add -m "idea"                # creates b1 (floating baseline)
lineage add -m "tweak lr" --from b0  # creates b0a (diff vs b0)
lineage diff b0 b0a                  # see what changed
lineage revert b0a                   # restore workspace to b0a
lineage log b0a loss=2.91            # record a metric
lineage note b0a                     # edit notes for b0a
lineage web                          # open the graph in your browser
lineage remove b1                    # delete a leaf
```

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
| `lineage web [--port N] [--metric NAME] [--no-browser]` | Launch the local graph UI in your browser. |

Run `lineage <command> --help` for options.

The web UI can also manage the graph directly: right-click the canvas for a
**New experiment** (floating baseline `bN`, no parent edge), right-click
a node for **New child** (nested under it with a path id like `b0a`), and
each node offers **Log** (record `key=value` metrics), **Diff vs parent**,
**Connect** (right-click → Connect to…, then click the new parent — or
drag an edge's dot onto another node; the node is renamed to a path
id under its new parent, and a connected snapshot is collapsed to a diff
against that parent whenever it round-trips exactly), **Focus**, **Unconnect** (renamed back to a fresh
floating `bN`), and **Remove** (asks before deleting descendants).

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

---

## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT
