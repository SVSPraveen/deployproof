# DeployProof Architectural Decisions (DECISIONS.md)

*Document updated: August 28, 2026*  
*Scope: V1 Diff-Scoping Strategy, Two-Tier Mutation Architecture & Edge-Case Validation*

---

## 1. Diff-Scoping Strategy Decision

### The Problem
AI-assisted development happens in rapid iterations. A developer may run `deployproof check` at different points in their workflow:
- **Mid-session**: The AI IDE just edited 2 files in the working directory; nothing has been staged or committed yet.
- **Post-commit**: The developer committed the changes locally and wants to run a final check before pushing.
- **CI / Pull Request**: A CI pipeline wants to test all commits introduced in a feature branch against the base branch (`main`).

Mutation testing is computationally expensive if run across an entire repository. DeployProof must scope execution strictly to the files changed in the active session without crashing on edge cases (fresh repos, single-commit repos, uncommitted edits, or non-git folders).

---

### Comparison of Evaluated Options

| Option | How it Works | Strengths | Failure Modes & Weaknesses |
|---|---|---|---|
| **1. Diff against default branch (`main`/`master`)** | `git diff main...HEAD` | Captures full branch delta for PRs. | Fails if `main` branch does not exist locally; fails on fresh repos before first push; ignores uncommitted working-tree edits; too broad for long-lived branches. |
| **2. Diff against `HEAD~1` (last commit only)** | `git diff HEAD~1` | Fast; captures the immediate last commit. | Crashes with fatal git error on fresh repositories with only 1 commit; completely ignores unstaged/staged working-tree changes mid-session. |
| **3. `--base <ref>` flag** | `git diff <ref>...HEAD` | Precise and essential for CI / PR pipelines. | As a mandatory requirement, introduces CLI friction for local solo developers who just want to run `deployproof check`. |
| **4. Diff against working tree (uncommitted changes)** | `git diff HEAD` + untracked | Directly matches mid-session AI edits before committing. | If the developer commits their files *before* running `deployproof check`, working-tree diff produces 0 files. |

---

### The Chosen Strategy: Smart Session Cascade with `--base` Override

To deliver a zero-friction experience for solo developers while supporting CI workflows, DeployProof adopts a **3-Tier Smart Session Cascade**:

```
                              deployproof check
                                      │
                         Is --base <ref> provided?
                                ├── YES ──► Diff <base> against working tree / HEAD
                                │
                                └── NO (Default Cascade)
                                      │
                     Step 1: Check Working Tree
                     (Unstaged + Staged + Untracked .py files)
                                      │
                           Are changed .py files found?
                                ├── YES ──► Scope mutation testing to these files
                                │
                                └── NO (Working tree is clean)
                                      │
                     Step 2: Check Latest Commit (HEAD)
                     (git diff-tree --root or HEAD~1 if history exists)
                                      │
                           Are changed .py files found?
                                ├── YES ──► Scope mutation testing to these files
                                │
                                └── NO
                                      │
                     Step 3: Safe Graceful Messaging
                     (Inform user working tree is clean, exit 0, no crash)
```

#### Safe Failure & Edge-Case Handling:
1. **Not a Git Repository**: If executed outside a git repo, DeployProof prints:
   `Error: Not a git repository. Initialize git or specify files with --files.`
   (Clean exit, zero Python tracebacks).
2. **Fresh Repository (0 commits)**: Untracked and staged `.py` files in the working tree are discovered via `git status --porcelain`. If no files are modified, it reports:
   `No modified Python files detected in current session.`
3. **Single-Commit Repository (1 commit, clean tree)**: When checking `HEAD`, DeployProof safely inspects root commit files using `git diff-tree --root` without invoking `HEAD~1` (which would error in git).
4. **Invalid `--base <ref>`**: If an invalid base ref is given (e.g. `--base non-existent`), DeployProof prints:
   `Error: Git reference 'non-existent' does not exist.`

---

## 2. Two-Tier Mutation System Architecture

### Tier 1: Local Pre-Check (Approximate AST Mutator)
- **Role**: Fast pre-commit sanity check running locally across all OS environments (Windows, macOS, Linux).
- **Labeling**: Every terminal report is explicitly labeled:  
  `LOCAL PRE-CHECK (approximate) — not the verified score`
- **Known Limitations**:
  - This is a lightweight AST mutator implemented in DeployProof.
  - Its operator coverage is currently limited to basic `Compare`, `BinOp`, `BoolOp`, `AugAssign`, and `Constant` mutations.
  - It does NOT mutate advanced language semantics (e.g. ternary branches inside f-strings, walrus expressions, async/await coroutine lifecycle, pattern match structures, yield statements).
  - Line-number snippet reconstruction can drift when `ast.unparse()` re-formats multi-line constructs.

### Tier 2: Verified Authoritative Score (`mutmut` in CI)
- **Role**: The official, authoritative mutation score referenced publicly for the repository.
- **Environment**: Executes in GitHub Actions on `ubuntu-latest` where `mutmut` runs natively with full POSIX process isolation and coverage tracking.
- **Workflow**: Triggered automatically on push/PR, scoped to the session diff.

---

## 3. Tier 1 AST Mutator Edge-Case Validation Findings

We tested the Tier 1 AST mutator against 7 advanced Python language constructs to document exact capabilities, omissions, and failure modes:

| Construct Tested | Fixture Pattern | Mutants Generated | Handled Correctly | Silently Skipped (Omissions) | Crashes |
|---|---|---|---|---|---|
| **Decorators** | `@lru_cache(maxsize=128)`<br>`@dec(threshold=50, is_enabled=False)` | 7 | Mutated function body arithmetic/constants and literal arguments inside decorator calls (`maxsize=129`, `threshold=51`, `is_enabled=True`). | Does not mutate decorator presence (e.g. stripping or replacing decorators). Line snippet alignment drifted on unparse. | 0 |
| **F-strings** | `f"User: {name}, Status: {'Admin' if is_active else 'Guest'}, High: {score > 100}, Next: {score + 1}"` | 4 | Mutated binary operators and comparisons inside embedded `{}` expressions (`score <= 100`, `score - 1`). | **Silently skipped** ternary conditions (`'Admin' if is_active else 'Guest'`) and string literal interpolations. | 0 |
| **Walrus Operator** | `if (n := len(items)) > 10:` | 5 | Mutated outer comparison (`> 10` → `<= 10`) and downstream arithmetic. | **Silently skipped** walrus assignment expression target and binding semantics. | 0 |
| **Async / Await** | `async def fetch(): await client.get()` | 5 | Mutated inner comparison (`<= 0`), boolean flags, and `is None` checks. | **Silently skipped** `await` keyword operations (e.g. dropping `await` or altering coroutine resolution). | 0 |
| **Comprehensions** | `[x * 2 for x in items if x > 0 and x % 2 == 0]`<br>`{k: v for k, v in d.items() if v != None}` | 15 | Mutated comprehension body expressions, modulo arithmetic, comparison filters, and boolean `and`/`or` chains. | **Silently skipped** comprehension structure (e.g. mutating list comp to empty generator or swapping key/value in dict comp). | 0 |
| **Match Statements** | `case {"action": "delete", "id": uid} if uid > 0:`<br>`case [x, y] if x == y:` | 3 | Mutated match case guard expressions (`if uid <= 0`, `if x != y`). | **Silently skipped** structural pattern shapes (mapping patterns, sequence patterns, literal values in patterns). | 0 |
| **Generators / Yield** | `while count < limit:`<br>`  yield count * 10` | 10 | Mutated while-loop comparisons, modulo checks, yielded expression arithmetic, and augmented assignments (`+=` → `-=`). | **Silently skipped** `yield` statement semantics (e.g. mutating `yield` to `return` or removing `yield`). | 0 |

### Summary of Edge-Case Analysis:
1. **Zero Hard Crashes**: `ast.parse` and `ast.unparse` successfully parsed and regenerated valid Python ASTs across all 7 Python 3.10+ constructs without throwing unhandled exceptions.
2. **Silent Skipping of Construct-Specific Semantics**: The mutator only mutates nested `Compare`, `BinOp`, `BoolOp`, and `Constant` nodes that happen to be children of these constructs. It **silently omits** structural mutations specific to walrus bindings, f-string ternaries, match pattern schemas, await removal, and generator yields.
3. **Validation Conclusion**: Tier 1 is suitable strictly as a fast local pre-check for basic logic errors; Tier 2 (`mutmut` in CI) remains mandatory for verified mutation scoring.
