# DeployProof — Full Scope

# DeployProof — Full Scope

*Name locked in: DeployProof. Repo live: github.com/SVSPraveen/deployproof. `pip install deployproof` confirmed as the install command. Last fact-checked: August 28, 2026.*

---

## 1. The Problem, Stated Plainly

Solo and small-team developers now ship large amounts of AI-generated code without the review capacity to catch what's wrong with it. This isn't a personal failing — it's a documented, industry-wide gap:

- CodeRabbit's December 2025 analysis of 470 real-world open-source pull requests found AI-co-authored code carries **~1.7x more issues overall** than human-only code — logic/correctness errors 75% more common, error-handling gaps ~2x more common, and security vulnerabilities **up to 2.74x higher for XSS specifically** (not a flat "2.74x more vulnerabilities" across the board — that's the peak category, not the average).
- A systematic review of AI-assisted coding workflows (ICSE 2026) found QA is the most overlooked dimension of the pipeline.
- **Test coverage lies.** A peer-reviewed study on LLM-generated tests (arXiv:2506.02954, HumanEval-Java) found a suite with 100% line/branch coverage scored only **4% on mutation testing** — it ran every line but caught almost nothing (missed cases like leap-year date handling). This is real and citable, not an urban legend.
- **Dependency hallucination ("slopsquatting")** is a live, growing attack class: open-source models hallucinate package names at an average **21.7%** rate, with some CodeLlama-family configurations exceeding **33%** (Spracklen et al., 576,000-sample study). **43% of hallucinated names reappear on identical prompts** — predictable enough that attackers pre-register them with malware inside. 8.7% of hallucinated Python package names turn out to be valid *npm* package names — a cross-registry confusion angle worth a check of its own. One hallucinated npm package (`react-codeshift`) already propagated through 237 repos via an AI agent's own skill file, with nobody deliberately planting it.
- **Agent sandbox-escape bugs ("GhostApproval")** hit six major coding tools at once, disclosed by Wiz Research on July 8, 2026: Amazon Q Developer, Claude Code, Augment, Cursor, Google Antigravity, and Windsurf. It's a symlink trick (CWE-61) combined with the UI showing the *decoy* filename instead of the resolved path (CWE-451) — in at least one tested case the agent's own reasoning explicitly identified the real target while the human-facing approval prompt still showed the fake one. **As of this writing:** Cursor is patched (CVE-2026-50549, CVSS 9.8, fixed in v3.0), AWS's Language Servers are patched (CVE-2026-12958, CVSS 7.8), Google Antigravity is patched (no CVE assigned yet). Augment and Windsurf are unpatched. Anthropic has stated it does not consider Claude Code's behavior in this report to be a vulnerability — though a related symlink-following sandbox-escape issue in Claude Code has separately been tracked as CVE-2026-39861 by a third-party researcher. **Verify current patch status yourself before you cite this publicly** — it's a live, moving situation and this file will go stale.
- AI-assisted commits leak secrets at **roughly 2x the baseline rate** (GitGuardian 2026: 3.2% of AI-assisted commits vs. 1.5% baseline across all public GitHub commits). Correction from the earlier draft of this doc: it's "~2x," not "2–3.2x" — 3.2% is the AI-assisted leak *rate itself*, not a multiplier.

**The core structural problem:** asking the AI IDE itself "is this ready?" doesn't work, because a verifier built at the same capability as the generator shares its blind spots. You need a check that doesn't ask an LLM's opinion at all.

---

## 1.5 Competitive Landscape (checked directly against live sites/repos, not assumed)

More players exist in this space than the last pass found. Know all of them before building.

**Ratchet CLI** (ratchetcli.com, github.com/kcemate/ratchet) — solo-founder-built, live, actively updated.
- Confirmed directly from the current site: **"Built and tested for TypeScript and JavaScript repositories."** Still JS/TS only — Python is genuinely open ground.
- Covers: security anti-patterns, type holes, missing error handling, coverage gaps (not mutation score), performance issues, complexity/architecture drift.
- Free "Community" tier: unlimited local scans, CI/JSON/SARIF output, BYOK AI review, MIT-licensed core. Paid: Pro $19/mo (autonomous test-gated auto-fix via `ratchet torque`), Team $79/mo. There's now also a **$2,500 fixed-price "Release Gate"** human-expert-review add-on — a services product layered on top of the CLI, not something DeployProof needs to compete with.
- Does **not** do: real mutation testing, slopsquatting detection, or the 2026 AI-IDE-specific CVE classes (GhostApproval-style sandbox escape, config/rule-file injection).

**blastradius-cli** (PyPI, Apache 2.0) — bigger than the earlier draft of this doc assumed. Directly from the PyPI listing: it's **already multi-language** — "Python, JavaScript/TypeScript, Go, Ruby, Rust, Java, PHP, and more" — and ships a persistent SQLite temporal graph, semantic symbol search, git-history-aware blast-radius scoring, and a **10-tool MCP server** plus a pre-commit hook and `CLAUDE.md` injection mode.
- This changes the wrapping story: it's not just "impact map for Python," it's infrastructure DeployProof could call *per-language for free*, out of the box, across most of your V1→Phase 4 roadmap. Worth wrapping its MCP server directly rather than shelling out to the CLI.

**Mutahunter** (github.com/codeintegrity-ai/mutahunter, PyPI, AGPL-3.0) — a real, existing "language-agnostic" mutation testing tool, ~286 GitHub stars. Important distinction: it uses an **LLM to generate the mutants themselves** ("context-aware fault injection"), which is a different model from wrapping deterministic mutators like Stryker/PIT/mutmut. This is not a full competitor to DeployProof's mutation-score check — it's adjacent, and worth a line in your README explaining why DeployProof deliberately doesn't do this (LLM-generated mutants reintroduce the "verifier shares the generator's blind spots" problem Section 1 argues against). But it proves language-agnostic mutation tooling has market interest, so cite it as validation, not just as competition.

**slopcheck** — an open-source CLI mentioned in current security writing as sitting "at the install boundary" checking dependency names against the real registry before `pip`/`npm` fires. This is a direct, narrower competitor to just the dependency-existence-check half of your slopsquatting feature. It does not appear to do registration-age analysis (the actual slopsquatting tell per your own Section 1) — check its repo directly before Phase 2 to confirm what it does and doesn't cover, the same way you already checked Ratchet and blastradius.

**The real, verified gap, after checking all four:** nobody free covers Python-first (or multi-language) mutation testing **using real deterministic mutators** + slopsquatting detection with registration-age analysis + the specific AI-IDE CVE checks (GhostApproval-class, config injection), in one tool, with zero paywall on the advanced features. That gap still holds. It's narrower than "nobody's doing AI code quality tools" — plenty are — but the specific combination, at the specific rigor level (deterministic scoring, no LLM in the scoring path), free forever, is still open.

---

## 1.6 Tool Currency Check — is everything you'd wrap actually alive?

You asked directly, so here's the verification, tool by tool, checked against live release pages (not memory) on August 28, 2026. This matters because a scope built on an abandoned dependency is a trap — you'd be shipping on top of something that stops getting security patches.

| Tool | Last verified release | Verdict |
|---|---|---|
| `mutmut` (Python) | v3.x line, PyPI page updated 2026-06-23, 62 published versions | Actively maintained. Already has a community MCP server (`mutmut-mcp`) — worth knowing about for your own architecture. |
| `cosmic-ray` (Python) | Established, slower-moving than mutmut | Usable as a fallback/alternative, mutmut is the safer default pick. |
| StrykerJS (JS/TS) | v7.0, added Vitest + Node Tap support | Actively maintained, industry standard. |
| PIT / pitest (Java) | Last release June 18, 2026 (Maven Central); mirror updated Aug 4, 2026 | Actively maintained, "gold standard" for JVM. |
| `cargo-mutants` (Rust) | Last release June 2, 2026 | Actively maintained, frequent releases. |
| Gremlins (Go) | Still pre-1.0 (0.x), Docker image updated ~4 months ago | Real and working, but the maintainers' own docs say it "doesn't work very well on very big Go modules" and config isn't stable across minor versions yet. Budget for this — don't promise Go parity with the same confidence as Python/JS/Java. |
| `mutant` gem (Ruby) | v0.15.1, March 2026 | Actively maintained. |
| Infection / Humbug (PHP) | Active GitHub org, current docs | Actively maintained. |
| `blastradius-cli` | Current PyPI listing, multi-language, includes MCP server | Actively maintained, worth wrapping directly. |

**Bottom line: every tool in your V1 and Phase 4-5 roadmap is alive and current, except Go's Gremlins, which is real but genuinely earlier-stage than the rest.** Nothing here forces you to build a mutation engine from scratch — that was already the right call, and it's now a verified one instead of an assumed one.

---

## 1.7 How Someone Actually Uses DeployProof (once it's built)

You asked for this directly because it's easy to spec features and skip what using the thing actually feels like. Here's the real flow, end to end:

1. **Install once** — `pip install deployproof` (or the equivalent for whatever language ecosystem they're in, once Phase 4 lands). No account, no dashboard, no signup — matching Ratchet CLI's "local by default" model, which is table stakes now, not a differentiator.
2. **Point it at a repo** — `deployproof init` auto-detects the language and test runner, same idea as Ratchet's `ratchet init`.
3. **Run it after any AI agent session** — `deployproof check`, either manually or as a hook the agent itself calls at the end of a session (this is exactly what Section 11's "native integration" aspiration is for, later).
4. **Read one number and a plain list** — mutation score, plus the exact surviving mutants (the specific lines your tests didn't actually verify), plus any security/dependency flags. No dashboard to log into.
5. **Fix what's flagged** — either by hand, or by feeding the surviving-mutant list straight back into the same AI IDE as a prompt ("here's what my tests missed, write tests that catch these"). This closes the loop instead of just reporting a number and walking away.
6. **Re-run until it clears the threshold** — same command, fast because it's scoped to the git diff, not the whole repo.
7. **Optionally, wire it into CI** — the GitHub Action (Phase 5) blocks the merge automatically if the score drops below whatever threshold the team sets, so it doesn't depend on a human remembering to run it.

The whole point, per your own Section 2, is that step 4 never involves an LLM call — the number is the same number no matter who runs it or when.

---

## 2. Core Principle

Every check in this tool must be **deterministic and reproducible** — the same input always produces the same output, verifiable by a stranger with no LLM call required in the scoring path. This is the one thing you've already proven you can build well (Finance-RAG-Copilot's evaluator). It's the whole differentiator, and it's also the reason Mutahunter (above) isn't really the same category of tool even though it looks adjacent on a feature list.

**Positioning: free forever, no paid tier, ever.** Not a generous free tier with the good parts locked behind a paywall (like Ratchet CLI) — everything, including whatever would normally be the "Pro" features, stays free. The mission is explicit: built by a solo dev, for solo devs, because the existing good tools started charging and that shouldn't be the thing standing between a solo developer and knowing their code is safe to ship.

---

## 3. Full Feature Scope

### A. Does it actually work
- **Mutation score, not coverage** — wraps existing, *deterministic* mutation testers, scoped to just the git-diff'd files from the latest AI session, not the whole repo. (See Section 6 for the per-language tool map.)
- **AI-specific static analysis** — a curated ruleset (not generic linting) targeting known AI failure patterns: control-flow gaps, missing null/bounds checks, concurrency bugs, silently swallowed exceptions.
- **Flaky vs. real bug differentiation** — reruns failing tests N times before flagging, since AI-assisted test suites are more prone to non-deterministic assertions.
- **Behavioral diff against the last working version** — flags silent scope drift: places the AI changed that nobody asked it to touch.

### B. Is it safe to run / ship
- **Symlink / sandbox-escape scanner** — flags any symlink in a repo pointing outside its own directory (the GhostApproval attack primitive; CWE-61 + CWE-451 pattern specifically — check that the *displayed* path matches the *resolved* path, not just that a symlink exists).
- **Config/rule-file injection scanner** — scans `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, MCP configs, hook configs for suspicious embedded instructions.
- **Secrets-before-push scanner** — catches API keys/credentials before they leave the machine. Given the 2x AI-assisted leak rate is now hard data (GitGuardian 2026), this check earns its place in V1-adjacent priority, not just Phase 3.
- **Dependency existence + registration-age check** — for every new import: does it exist, and if so, was it registered suspiciously recently (the actual slopsquatting tell — existence alone is not enough, and existence-only is what slopcheck already does for free, so this needs the age analysis to differentiate).
- **Known-CVE scan** on every dependency that does resolve legitimately.

### C. Can you trust the pipeline itself
- **Attribution tracking** — tags which lines came from an AI agent session vs. a human edit, so a future bug can be traced to its source.
- **Hard automated gate** — blocks merge/deploy on its own; doesn't rely on a human reviewer's speed or attention, since reviewing AI code often takes longer than writing it.
- **Tool version/CVE check** — flags if the installed Claude Code / Cursor / Antigravity version predates a known-patched vulnerability. GhostApproval is your first real, concrete entry for this check — you now have actual CVE numbers and patch versions to encode (see Section 1), which is a much stronger V1-adjacent feature than it was as an abstract idea.

---

## 4. Architecture

```
Developer finishes an AI-agent coding session
        ↓
CLI/CI hook triggers: `deployproof run`
        ↓
┌─────────────────────────────┐
│ 1. Git diff scope resolver  │ → identifies exactly what changed this session
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ 2. Parallel check runners   │
│  - blastradius MCP (wrapped)│ → impact map, reused not rebuilt, already multi-language
│  - Mutation tester wrapper  │ → language-dispatched, see Section 6 table
│  - AI-pattern static linter │
│  - Symlink/sandbox scanner  │
│  - Config injection scanner │
│  - Secrets scanner          │
│  - Dependency/slopsquat check (existence + registration-age, not just existence)
│  - CVE scan (deps + tool)   │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ 3. Deterministic scorer     │ → no LLM call; pure math/rule aggregation
└──────────────┬──────────────┘
               ↓
   One number + a plain list of what's unverified
        ↓
   Pass/fail gate (CI) or terminal report (local)
```

No component requires a new sandbox, a new IDE, or a new agent runtime. Everything wraps existing, proven tools and existing repos/pipelines — including other people's free, working tools where they already solved the problem well (blastradius-cli's MCP server for impact mapping).

---

## 5. V1 — Minimum Shippable Scope (build this first, nothing else)

Pick **one** language (Python, since it's what most of your own repos use, and since neither Ratchet CLI nor blastradius-cli owns Python's mutation-testing space) and **one** check:

0. First, actually run `pip install blastradius-cli` against a real repo of yours and read its MCP tool list. Don't build a competing impact-map — decide whether to call its MCP server directly from your CLI or shell out to it.
1. Also check `slopcheck`'s repo directly (same rigor you already applied to Ratchet and blastradius) before you build the dependency-existence half of Phase 2 — confirm exactly what it covers so you're not duplicating it, and scope your registration-age analysis as the differentiator.
2. Mutation-score wrapper around `mutmut` (or `cosmic-ray`), scoped to git-diff'd files only.
3. Output: a single percentage + list of surviving mutants (bugs your tests missed).
4. Ship as a CLI: `pip install deployproof && deployproof check`.
5. Test it against your own SPrav Job AI or Finance-RAG-Copilot repo first — you already know where the real bugs are, so you can verify the tool actually finds them.

Target: working, tested, and posted publicly within one to two weeks — not months.

**On "can I do all languages from the start" — the honest answer is below, but the short version stays the same: no, not for V1.** A mutation-testing wrapper that's half-working across five languages will lose to a mutation-testing wrapper that's fully working, fast, and trustworthy in one. Ratchet CLI is JS/TS-only and has real traction; that's evidence *for* narrow-and-solid, not against it.

### 5.1 "Version 1" vs. "the version you actually upload first" — these don't have to be identical

You asked this directly and it's a fair challenge to the plan: a mutation-score-only tool is a genuinely strong *engineering* V1, but it's a thin *launch* story on its own — "here's a percentage" doesn't demo as well as "here's a percentage, and also it just caught a symlink trap and a hardcoded API key." Two real options, honestly weighed:

- **Option A — ship strictly what Section 5 says, nothing more.** Fastest to real, working, trustworthy software. Lowest risk of missing your own 1–2 week target. Weaker launch hook on its own.
- **Option B — V1 core (mutation score) + one fast, rule-based check bolted on before the first public post.** The secrets-before-push scanner and the symlink/GhostApproval-pattern scanner are both good candidates for this: neither needs new infrastructure, both are pattern-matching over files (not slow mutation runs), and both can be built and stress-tested in days, not weeks, using the tools you already verified above. This turns the launch post from "a mutation-score number" into "a mutation-score number, and it also would have caught a real, current-CVE-class vulnerability" — which is a much stronger Show HN / r/LocalLLaMA hook, and ties directly into the still-live GhostApproval story from Section 1.

**Recommendation: Option B, but cap it there.** Don't add a third check just because you can — the whole discipline in your own Section 6 ("one working thing beats five half-built ones") is the thing to protect. If day 10 arrives and the second check isn't stress-test-clean, ship Option A instead of slipping the deadline. The deadline matters more than the extra feature.

Either way, the stress-test folder (Section 7) is what actually earns you attention on launch day — build at least the fixtures for whichever checks you ship, even in their smallest form, since "clone this and watch it catch every planted bug" is a stronger post than a feature list regardless of how many checks you launch with.

### 5.1.5 Free vs. paid — decided once, stated plainly

This isn't a new decision — Section 2 already made it ("free forever, no paid tier, ever") as the core differentiator against Ratchet CLI's paywalled advanced features. Restating the reasoning here since it came up directly:

- **Free (MIT), forever, no tier:** matches the stated mission, removes all install friction (directly serves the "more installs, more stars" goal), and security/verification tooling specifically earns more trust open than closed — people are more willing to let a scanner touch their repo when they can read exactly what it does. Zero payment/billing/ToS overhead for a solo maintainer.
- **The honest cost:** no revenue means the recurring maintenance work (the slopsquatting registry-age data source flagged in Section 10 as needing "upkeep, not a one-time build") is unfunded time. That's a real, ongoing cost, not a one-time build cost.
- **The actual answer, already in this doc:** stay free forever for the core product — that's the differentiator and the mission — and use Section 11's own "Sustainability without breaking free forever" plan (GitHub Sponsors / Open Collective, opt-in, never gated) if and when maintenance load actually requires it. Don't decide on payment structure now; there's nothing to fund yet. Revisit only after Section 9's success metrics show real usage.

### 5.2 Is the name available? (checked, not assumed)

- **GitHub:** No exact `deployproof` repo or org found in search. Close neighbors exist (`deploypro`, `devproof`, `deployra`) but nothing that collides directly.
- **PyPI / npm:** No exact `deployproof` package found in search on either registry.
- **Domain:** `deployproof.com` is an existing registration — but from a 2007 U.S. veterans'-business-continuity program ("Deploy Proof Your Business"), completely unrelated to software tooling and very likely dormant. Worth a direct, live check on the domain before you count on it, and worth having `.dev` or `.io` as a backup regardless — dev-tool audiences read `.dev` as more credible than `.com` anyway.
- **Caveat, stated plainly:** search results are a good signal, not a guarantee — a search index can miss something registered recently or something that's unindexed. Before you commit, do the three direct checks yourself the day you're ready to claim it: `pip install deployproof` (should fail/404 if free), the GitHub org creation page, and an npm `search` — takes five minutes and removes all doubt. Names in this space get squatted fast once a project starts getting attention, so claim GitHub + PyPI the same day you decide, even before the code is ready.
- **Does the name suit the project?** Yes — it does real work as a name. "Deploy" signals the ship-readiness angle directly, "Proof" signals evidence/verification rather than opinion, which lines up with your own Core Principle in Section 2 (deterministic, no LLM opinion in the scoring path). It reads as a noun a CI badge could plausibly say ("DeployProof: 94%"), which matters for the README badge moment Ratchet CLI already leans on. No notes against it.

**Cost clarification, since this caused real confusion:** claiming a GitHub repo/org name, a PyPI package name, and an npm package name are all **free** — an account plus claiming the name, nothing more. The only thing that costs money is the `.com` domain (~$12–15/yr), and it isn't needed to ship or distribute a CLI tool. `deployproof.com` is owned by an unrelated, almost-certainly-inactive 2007 veterans'-business site — not a software trademark, not a blocker, and not something you need to buy or fight over to start. Claim the free ones (GitHub, PyPI, npm) now; revisit a domain only if the project gets real traction. (General guidance, not legal advice — for a free, non-commercial open-source project the realistic risk here is low; a lawyer would only be worth involving if this became a funded commercial product later.)

---

## 6. Roadmap After V1 — with a real per-language tool map

This is the update that answers "can I do it for all languages" concretely: here's what each language actually needs, verified against what exists and is maintained today.

| Language | Deterministic mutation tester | Maturity (as of Aug 2026) |
|---|---|---|
| Python | `mutmut`, `cosmic-ray` | Mature, this is your V1 |
| JavaScript / TypeScript | Stryker (StrykerJS) | Mature, industry-standard — but this is Ratchet CLI's exact home turf |
| Java | PIT (pitest) | Mature, long-established, well-documented |
| C# / .NET | Stryker.NET | Mature |
| Go | Gremlins | Real and maintained, but "younger than Stryker/PIT — expect rougher edges" per current guides. Budget more integration time here. |
| Rust | `cargo-mutants` | Maintained, community-standard |
| Ruby | `mutant` gem | Mature |
| PHP | Humbug (Infection) | Mature |

- **Phase 2:** Add the slopsquatting/dependency checker with **registration-age analysis specifically** (the piece slopcheck doesn't appear to cover) — highest-novelty, most current threat, strong hook for a launch post.
- **Phase 3:** Add the security scanners (symlink/GhostApproval-pattern, config injection, secrets). You now have real CVE numbers (CVE-2026-50549, CVE-2026-12958, CVE-2026-39861) to encode as concrete test fixtures instead of an abstract "symlink trap" — this makes Section 7's stress-test folder much stronger.
- **Phase 4:** Multi-language support. Order by (a) tool maturity above and (b) developer population: JS/TS via Stryker is the largest population but also Ratchet's territory, so going there means competing head-on rather than filling a gap — decide deliberately whether that's the move, versus going to Java or Go next where there's genuinely nobody free doing this yet. Go deserves an explicit maturity caveat in your own docs, since Gremlins itself has rougher edges than Stryker/PIT.
- **Phase 5:** CI integration (GitHub Action) + the automated gate.

Build and stress-test each phase fully before starting the next — one working thing beats five half-built ones, proven the expensive way already.

---

## 7. Stress-Test Layer (build alongside every phase, not after)

A folder of deliberately broken test repos, one per check:
- One with a planted mutation-surviving bug
- One with a GhostApproval-style symlink trap — now buildable as a faithful reproduction using the actual disclosed pattern (decoy filename in the approval UI vs. resolved symlink target), not a guess
- One with a poisoned `CLAUDE.md`
- One with a fake hallucinated-looking dependency, ideally with a fabricated-but-plausible registration date to test the age-analysis logic specifically
- One with a planted secret

Run every check against this folder in CI. If a check doesn't catch its own planted bug, it doesn't ship. This folder is also your best marketing asset later: "clone this, run our tool, see it catch every planted bug yourself."

---

## 8. Distribution Plan

- Open source, MIT or similar — the methodology being public *is* the credibility.
- Launch post: Show HN + r/LocalLLaMA + relevant Discord communities, framed around one honest finding from your own testing ("here's what our mutation score found in a real AI-generated repo"), not a feature list.
- Direct outreach to Claude Code / Cursor / Antigravity communities once V1 is stable — these are exactly the audiences already anxious about this, per the CVE research, and GhostApproval specifically is a live, still-partially-unpatched story as of this writing, which makes it a genuinely timely hook, not a stale one.
- Once mature enough to compare directly: an honest, factual post benchmarking against Ratchet CLI's own published scoring on the same test repos — "same category, Python-first, real mutation score instead of coverage, and the advanced features stay free" is a real, checkable claim, not marketing spin, as long as the numbers are real.

---

## 9. Success Metrics (deterministic, matching the tool's own philosophy)

- Does the stress-test folder pass 100% (every planted bug caught)?
- Real installs/CLI runs (not stars — stars are vanity, usage is signal).
- At least one real bug found in your *own* existing repos that you didn't already know about.
- First external contributor or first external bug report — the first sign someone besides you is actually relying on it.

---

## 10. Honest Risks

- Mutation testing can be slow on large codebases — scoping to git-diff only is what keeps this usable, don't skip that.
- Slopsquatting detection needs a maintained, current registry-age data source — this will require upkeep, not a one-time build. slopcheck existing as prior art for the existence-check half means you have less to build there, but the age-analysis differentiator is still yours to maintain.
- You will get pushback if any check produces a false positive against a popular tool's output — treat every dispute as a reason to publish your exact methodology, not defend it emotionally.
- GhostApproval-class findings are genuinely contested — Anthropic disputes it's a vulnerability at all for Claude Code. If DeployProof flags something in this category, be precise about what you're flagging (a symlink pattern that *could* enable UI-spoofed approval) rather than implying every vendor agrees it's a bug. Overclaiming here is the fastest way to lose credibility with exactly the audience you want.
- This is infrastructure, not a viral consumer app — growth will likely be slower and steadier than a consumer-app curve. That's fine. Steadier is also more durable.

---

## 11. Future Scope (aspirational — only after V1 through Phase 5 are real, working, and have real external users)

This section is placed last on purpose, and it stays untouched until the free, working, Python-first core is proven.

- **Native integration** — a direct plugin/extension inside Claude Code, Cursor, and Antigravity, so the check runs automatically at the end of every agent session instead of a manual CLI call.
- **Community-sourced stress-test library** — open the planted-bug test folder (Section 7) to contributions: any developer who finds a new AI-specific failure pattern submits it as a new test case, the way CVE databases grow through community disclosure.
- **Multi-language parity** — using the tool map in Section 6, once Python is genuinely solid and trusted, not before.
- **An educational layer** — not just "here's what's broken," but a plain-language explanation of *why*, so developers using it get better at spotting these patterns themselves over time.
- **Sustainability without breaking "free forever"** — optional GitHub Sponsors / Open Collective support if it ever needs more than personal time to maintain, never a paywalled tier.
- **A public registry, not just a tool** — an honest, versioned record of which AI-coding-agent versions produce cleaner code, and which failure patterns recur across tools.

None of this is a promise, and none of it starts before Section 5 is finished and real.

---

## What Changed From the Last Draft (read this before you build)

Quick diff so you know what to trust and what to re-verify closer to build time:

1. **Corrected a real error**: secrets leak rate is "~2x baseline" (3.2% vs 1.5%), not "2–3.2x" — the earlier draft conflated the rate with a multiplier.
2. **Corrected an overclaim**: the 2.74x security-vulnerability figure is specifically for XSS, not a blanket "security vulnerabilities are 2.74x higher."
3. **Added real CVE numbers** for GhostApproval (CVE-2026-50549, CVE-2026-12958, CVE-2026-39861) and current, checkable patch status per vendor — this was vague before and is now a much stronger V1-adjacent feature and stress-test case.
4. **Found two new adjacent tools** (Mutahunter, slopcheck) that weren't in the last competitive check — neither fully closes your gap, but both are worth reading before you build the overlapping feature, and both are worth an honest mention in your own README so nobody accuses you of not knowing your own space.
5. **blastradius-cli is bigger than assumed** — already multi-language with an MCP server, which changes how much of your Section 6 roadmap you can get "for free" by wrapping it well.
6. **Added the per-language mutation-tool map** (Section 6) so "all languages" has a concrete, honest answer instead of a vague aspiration.

This file will drift out of date the same way the last one did — GhostApproval patch status especially is likely to change within weeks. Re-check Section 1 and 1.5 directly before your Phase 3 and Phase 4 launches, not just once now.

**Second pass added:** a tool-currency check (1.6) confirming every mutation tester in the roadmap is actively maintained except Go's Gremlins (real, but pre-1.0 and rougher); a plain end-to-end usage flow (1.7); an honest "V1 vs. first-upload" split (5.1) recommending one fast rule-based check alongside the mutation-score core for launch impact, capped deliberately so it doesn't eat the 1–2 week deadline; and a name-availability check (5.2) — GitHub/PyPI/npm look clear, `deployproof.com` is an old, unrelated, likely-dormant registration worth a direct look before relying on it, and the name itself holds up on its own merits.
