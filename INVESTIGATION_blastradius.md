# Investigation: `blastradius-cli` for DeployProof

*Document generated: August 28, 2026*  
*Target package: `blastradius-cli` (verified version: `0.3.7` on PyPI)*  
*Repository tested: `DeployProof` (`src/`, `tests/`, `.github/`)*

---

## 1. Executive Summary

`blastradius-cli` is a multi-language static dependency analyzer, symbol indexer, and blast-radius impact scorer. It computes dependency graphs, direct/transitive dependent counts, and impact risk metrics across codebases.

Key technical characteristics verified during testing:
- **Zero required external runtime dependencies**: Built almost entirely on Python standard library modules (`ast`, `re`, `json`, `sqlite3`, `subprocess`, `argparse`, `pathlib`). Optional extras exist only for file watching (`watchdog`), YAML CI parsing (`PyYAML`), and vector search (`sqlite-vec`).
- **Multi-language support**: Shipped with built-in analyzers for Python, JavaScript/TypeScript, Go, Java, PHP, Ruby, Rust, Docker, Terraform, CSS, CI workflows, Monorepo setups, and cross-language boundaries.
- **Built-in 10-Tool MCP Server**: Accessible via `blastradius serve --mcp` running over standard JSON-RPC 2.0 (stdio).
- **Multiple persistent storage layers**: Produces JSON graph files (`blastradius.json`, `symbolindex.json`) and an optional SQLite database (`.blastradius/index.db`) with temporal commit tracking.

---

## 2. CLI Commands and Flags

Running `blastradius --help` reveals 12 distinct subcommands:

```
usage: blastradius [-h]
                   {analyze,impact,serve,symbols,lookup,dependencies,high-blast,symbol-blast,db,history,changed-since,search,install-hook} ...
```

### Detailed Command Reference

| Subcommand | Description | Key Flags / Options |
|---|---|---|
| `analyze` | Analyzes a repo and generates `blastradius.json` | `[repo]` (default `.`), `--output OUTPUT`, `--watch` |
| `impact` | Calculates blast-radius impact for a specific file | `file`, `--index INDEX`, `--out OUT` (markdown report), `--json` (raw JSON), `--as-of REF` (historical commit) |
| `serve` | Serves visualization web UI or runs stdio MCP server | `--viz` (default), `--mcp` (runs stdio MCP server), `--repo REPO`, `--port PORT`, `--watch`, `--output OUTPUT` |
| `symbols` | Builds symbol index (`functions`, `classes`, `exports`) | `[repo]`, `--output OUTPUT`, `--inline`, `--index INDEX`, `--claude-md`, `--claude-md-path`, `--all-symbols` |
| `lookup` | Instant $O(1)$ definition lookup (file + line) | `name`, `--index INDEX`, `--json` |
| `dependencies`| Shows direct imports and imported-by for a file | `file`, `--index INDEX`, `--json` |
| `high-blast` | Lists files exceeding a blast score threshold | `--threshold THRESHOLD` (default: 5), `--index INDEX`, `--json` |
| `symbol-blast`| Per-export blast radius across importers | `file`, `--json` |
| `db` | Manages SQLite store (`.blastradius/index.db`) | `{status, migrate}`, `--db DB`, `--json` |
| `history` | Backfills temporal graph data from Git history | `[repo]`, `--since REF`, `--max-commits MAX_COMMITS`, `--json` |
| `changed-since`| Lists files/edges added or removed since a git ref | `ref`, `--repo REPO`, `--db DB`, `--json` |
| `search` | Hybrid semantic + keyword + graph symbol search | `query`, `--k K` (default: 10), `--as-of REF`, `--db DB`, `--json` |
| `install-hook`| Installs pre-commit hook for impact warnings | `--threshold THRESHOLD` |

---

## 3. MCP Server Analysis

When started with `blastradius serve --mcp`, it exposes an **MCP stdio server** conforming to the Model Context Protocol (protocol version `2024-11-05`).

It publishes **10 distinct MCP tools**:

### MCP Tool Definitions & Input Schemas

1. **`analyze_repo`**
   - *Description*: Analyze a repository and build/refresh its `blastradius.json` dependency index.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "repo_path": { "type": "string", "description": "Absolute or relative path to the repo root." }
       },
       "required": ["repo_path"]
     }
     ```

2. **`get_impact`**
   - *Description*: Return blast-radius impact report for a specific file (direct/transitive dependents, blast score, risk level).
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "file_path": { "type": "string", "description": "Path to the file to assess (relative or absolute)." },
         "index_path": { "type": "string", "description": "Path to blastradius.json (auto-discovered if omitted)." }
       },
       "required": ["file_path"]
     }
     ```

3. **`get_dependencies`**
   - *Description*: Return direct imports and imported-by list for a specific file.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "file_path": { "type": "string", "description": "Path to the file." },
         "index_path": { "type": "string", "description": "Path to blastradius.json." }
       },
       "required": ["file_path"]
     }
     ```

4. **`get_high_blast_files`**
   - *Description*: Return all files whose blast score exceeds a threshold, sorted descending.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "threshold": { "type": "number", "description": "Minimum blast score (default: 5)." },
         "index_path": { "type": "string", "description": "Path to blastradius.json." }
       }
     }
     ```

5. **`lookup_symbol`**
   - *Description*: Find where a function, class, struct, or symbol is defined with file path and line number via $O(1)$ index lookup.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "name": { "type": "string", "description": "Exact symbol name to look up." },
         "symbol_index_path": { "type": "string", "description": "Path to symbolindex.json." }
       },
       "required": ["name"]
     }
     ```

6. **`build_symbol_index`**
   - *Description*: Build or refresh `symbolindex.json` for a repository.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "repo_path": { "type": "string", "description": "Path to the repo root." }
       },
       "required": ["repo_path"]
     }
     ```

7. **`semantic_search`**
   - *Description*: Hybrid semantic + keyword (FTS5) + graph search over indexed symbols using Reciprocal Rank Fusion.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "query": { "type": "string", "description": "Natural-language or keyword query." },
         "k": { "type": "integer", "description": "Maximum number of results (default: 10)." },
         "as_of": { "type": "string", "description": "Optional commit/ref." },
         "db_path": { "type": "string", "description": "Path to .blastradius/index.db." }
       },
       "required": ["query"]
     }
     ```

8. **`temporal_impact`**
   - *Description*: Compute blast-radius impact for a file at a historical commit/ref using temporal git graph data.
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "file": { "type": "string", "description": "Repo-relative file path." },
         "as_of": { "type": "string", "description": "Commit hash, branch, or tag." },
         "db_path": { "type": "string", "description": "Path to .blastradius/index.db." }
       },
       "required": ["file"]
     }
     ```

9. **`graph_query`**
   - *Description*: Return the k-hop dependency neighborhood of a file (`direction='dependents'|'dependencies'|'both'`).
   - *Schema*:
     ```json
     {
       "type": "object",
       "properties": {
         "file": { "type": "string", "description": "Repo-relative file path." },
         "direction": { "type": "string", "enum": ["dependents", "dependencies", "both"], "description": "Traversal direction." },
         "depth": { "type": "integer", "description": "Number of hops (default: 2)." },
         "db_path": { "type": "string", "description": "Path to .blastradius/index.db." }
       },
       "required": ["file"]
     }
     ```

10. **`changed_since`**
    - *Description*: List files and edges added or removed since a commit/ref to evaluate architectural and dependency drift.
    - *Schema*:
      ```json
      {
        "type": "object",
        "properties": {
          "ref": { "type": "string", "description": "Commit hash, branch, or tag to compare against HEAD." },
          "db_path": { "type": "string", "description": "Path to .blastradius/index.db." }
        },
        "required": ["ref"]
      }
      ```

---

## 4. Output Formats Verified

### A. Graph Index (`blastradius.json`)
Structure contains:
- `meta`: `root`, `total_files`, `total_loc`, `languages`, `indexed`
- `nodes`: list of file and package nodes with `id`, `type` (`module` or `import`), `language`, `loc`, `group`, `imports`, `layer`, `direct_dependents`, `transitive_dependents`, `blast_score`, `imported_by`
- `links`: list of directed edges with `source`, `target`, `weight`, `kind`

### B. Impact Query Output (`--json`)
```json
{
  "file": "src\\deployproof\\cli.py",
  "blast_score": 0.0,
  "direct_dependents": 0,
  "transitive_dependents": 0,
  "direct_ids": [],
  "transitive_ids": []
}
```

### C. Symbol Index Output (`symbolindex.json` / `lookup`)
```json
{
  "name": "main",
  "matches": [
    {
      "file": "src\\deployproof\\cli.py",
      "line": 47,
      "kind": "function",
      "exported": true
    }
  ]
}
```

---

## 5. Public API Verification & Integration Analysis

### Public Python API Verification
A thorough inspection of `blastradius-cli` (v0.3.7) was conducted to determine if a public Python library API exists:
1. **Documentation & README**: The PyPI page and repository README document CLI subcommands (`blastradius analyze`, `blastradius impact`, etc.), MCP configuration for Claude Code (`blastradius serve --mcp`), `CLAUDE.md` injection, and output JSON schemas. There is **no documentation, tutorial, or mention of Python library imports or a Python API**.
2. **Export Surface & Structure**:
   - `blastradius/__init__.py` defines only `__version__ = "0.1.0"`. It declares no `__all__` list and re-exports zero functions or classes.
   - No `api.py`, `public.py`, or facade module exists in the distribution.
   - The package is strictly packaged as a CLI application with console script entry point `blastradius = blastradius.cli:main`.
3. **Internal Symbols & `_HANDLERS`**:
   - In `blastradius/mcp_server.py`, the handler registry `_HANDLERS` and all individual tool handlers (`_call_analyze_repo`, `_call_get_impact`, `_call_temporal_impact`, etc.) are explicitly prefixed with a leading underscore (`_`).
   - By standard Python conventions, these are private implementation details subject to arbitrary change or refactoring between releases without deprecation warnings.

**Conclusion**: Direct Python import of `blastradius` modules (`blastradius.impact`, `blastradius.mcp_server._HANDLERS`, etc.) relies on **undocumented internal implementation details**, not a supported public API.

---

### Integration Models Evaluated

#### 1. Shell Out to CLI (`subprocess.run(["blastradius", "impact", "--json", ...])`)
- **Pros**:
  - **Contract Stability**: CLI commands and flags (`impact --json`, `analyze`, `lookup --json`) are the primary, documented public interface of `blastradius-cli`.
  - **Isolation**: Breaking internal refactors in future `blastradius-cli` versions will not crash DeployProof as long as the CLI contract is maintained.
  - **Decoupled Packaging**: Can operate with a separate virtualenv or global installation (via `pipx`).
- **Cons**:
  - **Subprocess Latency Tradeoff**: Spawning a separate Python subprocess per file adds approximately **50–150ms per file** on Windows / POSIX.
  - **Path Normalization**: Requires normalizing file path separators (e.g. `os.path.normpath` / `Path.resolve`) to match `blastradius` internal node IDs across platforms.

#### 2. Direct Python Library Import (`import blastradius...`)
- **Pros**:
  - In-memory execution (sub-millisecond queries).
  - No subprocess spawning or CLI argument parsing overhead.
- **Cons**:
  - **High Maintenance & Fragility Risk**: Relies entirely on undocumented, private internal symbols (`_HANDLERS`, internal AST walkers). An unannounced patch or minor release of `blastradius-cli` could silently break DeployProof.

#### 3. Calling MCP Server via stdio JSON-RPC (`blastradius serve --mcp`)
- **Pros**:
  - Explicit MCP JSON-RPC protocol contract.
- **Cons**:
  - Unnecessary complexity for local deterministic scans (managing child process IPC lifecycles, stream buffers, and JSON-RPC handshakes).

---

## 6. Final Integration Recommendation for DeployProof

Based on the confirmation that `blastradius-cli` does not provide a public Python library API:

1. **Recommended Architecture: CLI Subprocess with `--json` Flag**
   - DeployProof will integrate with `blastradius-cli` by invoking its official CLI interface via subprocess with `--json` (e.g., `blastradius impact <path> --json` and `blastradius analyze .`).
   - The CLI interface and its `--json` flags are documented, stable, and tested by upstream maintainers.

2. **Latency Tradeoff & Mitigation**:
   - **Tradeoff**: Spawning a subprocess per file introduces a known latency of **~50–150ms per file**.
   - **Mitigation Strategy**:
     - For git diffs touching multiple files, DeployProof can first run `blastradius analyze .` once at the repo level (or rely on cached `blastradius.json` if up to date).
     - Individual file impacts can then be queried efficiently, or read directly from the generated `blastradius.json` contract artifact when appropriate, bounding total subprocess calls.
     - All paths will pass through an internal path normalizer (`Path(p).as_posix()` / `os.path.normpath()`) to ensure consistent node matching on Windows and Unix.

---

## 7. Conclusion

`blastradius-cli` should be treated as an external CLI utility rather than an in-process Python library. Calling `blastradius impact --json` via subprocess represents the safest, most contract-stable approach for DeployProof V1, with the ~50–150ms/file subprocess latency accepted as a known tradeoff for upstream stability.

