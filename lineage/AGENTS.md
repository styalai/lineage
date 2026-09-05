# AGENTS.md — using `lineage` to track experiments

`lineage` versions a working directory as a graph of experiments. Each
experiment is either a full **snapshot** (byte copy of the workspace) or a
**diff** (unified patch against its parent). Use it to checkpoint before
risky changes, compare variants, and record metrics.

Copy this file into any project where you want agent-run experiments tracked.

## Typical workflow

```bash
cd your-project

lineage add -m "baseline"              # b0: first experiment, always a snapshot
# ... edit code, run training ...
lineage add -m "lr 3e-4"               # b1: floating baseline snapshot
lineage log b1 loss=2.91 acc=0.81      # record metrics (values are strings)

lineage add -m "quantize" --from b0    # b0a: attached child, diff vs b0
lineage diff b0 b0a                    # what changed between the two
lineage diff b0a --stat                # or: only change stats

lineage revert b0a --dry-run           # preview restoring b0a ...
lineage revert b0a                     # ... then actually restore it
lineage web --no-browser --port 5173   # inspect/manage the graph in a browser
```

## IDs: floating vs attached

- **Floating** experiments are numbered `b0` (root), `b1`, `b2`, … They have
  no parent edge and are always snapshots (self-contained).
- **Attached** experiments encode their position: parent id + a letter —
  `b0a` (child of `b0`), `b0aa` (child of `b0a`), `b2a`, … They are usually
  diffs against the parent.
- A bare `lineage add` always creates a **floating** baseline. Pass
  `--from <id>` (or `--snapshot`) to control the outcome:
  - `add --from b0` → attached child (`b0a`), diff vs `b0` by default.
  - `add --from b0 --snapshot` → attached child, full snapshot instead.
  - `add --detached` → explicitly floating (same as the default).

## Moves rename the node — re-read IDs afterwards

There is no separate "connect" CLI command; moves happen in `lineage web`
(right-click → Connect to… / Unconnect, or drag an edge dot). Moves rename:

- **Connect** `b2` under `b0a` → renamed to `b0ab` (subtree follows:
  its child becomes `b0aba`, …). A connected snapshot is collapsed to a
  diff against the new parent whenever it round-trips byte-identically
  (binary content keeps it a snapshot).
- **Unconnect** `b0ab` → renamed to a fresh floating `bN` (subtree
  re-suffixed under it). A detached diff is materialized into a standalone
  snapshot first, since its patch belonged to the old parent.

After any move, resolve the new IDs from the UI or `lineage web` output —
old IDs no longer exist.

## Command reference

| Command | Effect |
|---|---|
| `lineage add [-m MSG] [--from ID] [--snapshot] [--detached]` | Snapshot workspace as floating `bN`, or attach under `--from` (path id, diff by default). |
| `lineage log ID key=value …` | Record metrics. Any key; values stored as strings; quote values with spaces. |
| `lineage diff A [B] [--stat] [--files]` | Unified diff between two experiments, or between `A` and its parent. |
| `lineage revert ID [--dry-run]` | Restore workspace files to `ID`. Never deletes files that aren't in the target. |
| `lineage note ID [-m MSG] [--append]` | Edit notes (`$VISUAL`/`$EDITOR`, or non-interactive with `-m`). |
| `lineage remove ID [--recursive]` | Delete an experiment. Refuses when it has children unless `--recursive`. |
| `lineage web [--port N] [--no-browser] [--metric-a K] [--metric-b K]` | Local graph UI (default port 5173). Nodes show `first \| second` metric picks. |
| `lineage init [--for opencode\|claude\|codex\|all] [--force]` | Write this instruction file into another project (`AGENTS.md` for opencode/codex, `CLAUDE.md` for claude). |

## Rules

1. Prefer `add -m "<what changed>"` before any destructive or speculative
   edit, so `revert` can always undo.
2. Log the metrics that decide between variants (`log ID loss=…`) — don't
   rely on memory or chat history.
3. Never hand-edit or delete anything under `.lineage/`; use `remove`.
   To drop a whole history, delete the `.lineage/` directory itself.
4. `revert` overwrites tracked files but never deletes untracked ones;
   use `--dry-run` first when unsure.
5. Binary files are stored fine in snapshots but cannot be expressed in
   diffs — keep binaries in baselines, text in diffs.
6. One concept per experiment: checkpoint, then change, then `add`.
