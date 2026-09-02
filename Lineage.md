# 🧬 Lineage

**Track the lineage of your experiments.**  
A lightweight CLI to manage experiments as a **graph of snapshots and diffs**, without interfering with Git.

---

## ✨ Philosophy

- **Zero Git friction** → use Git normally
- **Workspace-first** → experiments come from your current files
- **Snapshots + diffs** → efficient and reproducible
- **Graph, not list** → each experiment has an ancestor
- **Deterministic IDs** → readable lineage paths

---

## 🧠 Core Concept

Each experiment is a **node in a graph**:

- Has an **ancestor** (parent)
- Stores either:
  - a **snapshot** (full copy)
  - or a **diff** (relative to ancestor)

---

## 🆔 Experiment ID System

### Root

```text
b0
```

---

### Child generation

Each child appends **one character** from a fixed alphabet:

```text
abcdefghijklmnopqrstuvwxyz@#&?%!0123456789
```

👉 Total: **42 possible children per node**

---

### Example

```text
b0
├── b0a
├── b0b
├── ...
├── b0z
├── b0@
├── b0#
├── ...
├── b0!
├── b00
├── ...
└── b09
```

---

### Deeper levels

```text
b0
└── b0a
    ├── b0aa
    ├── b0ab
    └── b0a0
```

---

### Rules

- Child index determines character
- Max **42 children per node**
- If exceeded → error

```text
❌ Cannot create experiment:
   parent b0a already has 42 children
```

---

### Parent inference

```text
parent(b0abc) = b0ab
```

---

## 📁 Folder Structure

```text
project/
  src/
  train.py

  .lineage/
    experiments/
      b0/
        snapshot/
        meta.json
        notes.md

      b0a/
        diff.patch
        meta.json
        notes.md
```

Add to `.gitignore`:

```text
.lineage/
```

---

## 🧩 Experiment Types

### 🟢 Snapshot

Full copy of workspace.

Used when:
- first experiment
- checkpoint

```text
b0/
  snapshot/
```

---

### 🔵 Diff

Stores changes from ancestor.

```text
b0a/
  diff.patch
```

---

## 🧠 Metadata (`meta.json`)

```json
{
  "id": "b0a",
  "parent": "b0",
  "type": "diff",
  "message": "quantize embedding",
  "created_at": "2026-09-02T10:00:00"
}
```

---

## ⚙️ CLI Commands

---

### ➕ `lineage add`

Create experiment from current workspace.

```bash
lineage add -m "quantize embed"
```

#### Behavior:
- Captures current files (including uncommitted)
- Finds parent (last experiment or `--from`)
- Assigns next ID using alphabet
- Stores:
  - snapshot (if needed)
  - otherwise diff vs ancestor

---

### 🔍 `lineage diff`

```bash
lineage diff b0 b0a
lineage diff b0a      # vs ancestor
```

Options:

```bash
--stat
--files
```

---

### 🔁 `lineage revert`

Restore workspace.

```bash
lineage revert b0a
```

Preview:

```bash
lineage revert b0a --dry-run
```

---

### ❌ `lineage remove`

```bash
lineage remove b0a
```

Options:

```bash
--recursive
--force
```

---

### 👀 `lineage list`

```bash
lineage list
```

Example:

```text
b0
├── b0a loss=3.2
├── b0b loss=3.1
└── b0c loss=2.9 ✅
```

---

### 📖 `lineage show`

```bash
lineage show b0a
```

---

### ✏️ `lineage note`

```bash
lineage note b0a
```

---

### 📊 `lineage log`

```bash
lineage log b0a --val-loss 2.91
```

---

### 🌳 `lineage graph`

```bash
lineage graph
```

---

### 🧹 `lineage gc`

```bash
lineage gc
```

---

## 🔄 Storage Strategy

- First experiment → snapshot  
- Next → diff vs ancestor  
- Periodically → snapshot checkpoint  

---

### Example

```text
b0 (snapshot)
 ↓
b0a (diff)
 ↓
b0aa (diff)
 ↓
b0ab (snapshot)
```

---

## ⚡ Diff Creation

```bash
diff -ruN parent_snapshot/ current_workspace/ > diff.patch
```

---

## 🔁 Reconstruction

To restore an experiment:

1. Find nearest snapshot ancestor  
2. Copy snapshot  
3. Apply diffs sequentially  

---

## 🔁 Apply / Revert

Apply:

```bash
patch -p1 < diff.patch
```

Revert:

```bash
patch -R -p1 < diff.patch
```

---

## 🧠 Workspace Rules

- Always uses current workspace
- Includes:
  - staged
  - unstaged
  - untracked files

- NEVER:
  - resets files
  - modifies git

---

## 🔒 Safety

- `.lineage/` is isolated
- deleting it does not affect project
- no Git dependency

---

## 💡 Optimizations

### Hardlink snapshots

```bash
cp -al project/ snapshot/
```

---

### Auto checkpoint

Create snapshot when:
- diff too large
- chain too long

---

## 🤖 Agent Integration

```bash
lineage run --from b0a -- python train.py
```

---

## 🎯 Goals

- Track experiment evolution
- Store reasoning
- Enable fast iteration
- Stay invisible to Git

---

## 🚀 Summary

- Experiments = graph
- IDs encode lineage
- Snapshot + diff hybrid
- Max 42 children per node
- Simple, fast, reproducible

---

**Lineage = experiments as a graph, not a list**