/**
 * DeployProof Documentation & Product Portal Interactive Engine
 * Created by SVS Praveen (https://svspraveen.vercel.app/)
 */

document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle();
  initTerminalTabs();
  initCopyButtons();
  initSearch();
  initScrollspy();
  initGateExplorer();
});

/* ==========================================================================
   1. Theme Toggle (Dark / Light Mode)
   ========================================================================== */
function initThemeToggle() {
  const toggleBtn = document.getElementById('theme-toggle');
  const themeIcon = document.getElementById('theme-icon');
  if (!toggleBtn) return;

  const currentTheme = localStorage.getItem('deployproof-theme') || 'light';
  if (currentTheme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
    if (themeIcon) themeIcon.textContent = '☀️';
  } else {
    document.documentElement.removeAttribute('data-theme');
    if (themeIcon) themeIcon.textContent = '🌙';
  }

  toggleBtn.addEventListener('click', () => {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('deployproof-theme', 'light');
      if (themeIcon) themeIcon.textContent = '🌙';
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('deployproof-theme', 'dark');
      if (themeIcon) themeIcon.textContent = '☀️';
    }
  });
}

/* ==========================================================================
   2. Interactive Terminal Playground
   ========================================================================== */
const terminalScenarios = {
  check: `
<span class="term-prompt">❯ deployproof check</span>
DeployProof: Initializing 4 isolated parallel workers for full repo mutation scan...
DeployProof: Running baseline test suite on 5 test file(s) (collecting coverage map)...
DeployProof: Baseline test run completed in 1.4s.

DeployProof: Running 44 mutants across 4 workers in parallel...
  <span class="term-success">[44/44 mutants | 2/2 files]</span> elapsed: 0m14s

Gate Verification Summary:
  <span class="term-success">✔</span> <b>Gate 1 (Mutation Testing)</b>   : <span class="term-success">PASSED (95.4% score)</span> [42/44 killed] (Threshold: 80.0%)
  <span class="term-success">✔</span> <b>Gate 2 (OWASP Top 10 SAST)</b>   : <span class="term-success">CLEAN</span> (0 vulnerabilities detected)
  <span class="term-success">✔</span> <b>Gate 3 (Secrets & Credentials)</b>: <span class="term-success">CLEAN</span> (0 hardcoded API keys/tokens)
  <span class="term-success">✔</span> <b>Gate 4 (Git History Scanner)</b>  : <span class="term-success">CLEAN</span> (0 leaked credentials across 50 commits)
  <span class="term-success">✔</span> <b>Gate 5 (OSV CVE & Slop-Check)</b> : <span class="term-success">CLEAN</span> (0 CVE advisories, all packages verified)
  <span class="term-success">✔</span> <b>Gate 6 (Symlink Sandbox Gate)</b> : <span class="term-success">CLEAN</span> (0 path traversal escapes)
  <span class="term-success">✔</span> <b>Gate 7 (Control Flow / Mocks)</b>: <span class="term-success">CLEAN</span> (0 swallowed exceptions)

====================================================================
<span class="term-success">🎉 ALL 7 GATES PASSED (Score: 95.4%) &bull; Ready to push & deploy!</span>
`,
  heal: `
<span class="term-prompt">❯ deployproof check --heal-tests</span>
DeployProof: Running 44 mutants across 4 workers in parallel...
Notice: 2 surviving mutants detected.

<span class="term-warn">Surviving Mutants:</span>
  [1] src/auth.py:14 (Missing 'roles' fallback)
      Original: <span class="term-badge">roles = payload.get("roles", [])</span>
      Mutated : <span class="term-err">roles = payload.get("roles", None)</span>

  [2] src/symlinks.py:108 (rstrip vs strip)
      Original: <span class="term-badge">raw_str = str(raw_target).strip()</span>
      Mutated : <span class="term-err">raw_str = str(raw_target).rstrip()</span>

<span class="term-success">[+] DeployProof Synthesized 2 self-healing test(s) in tests/test_deployproof_healed.py!</span>
    Synthesized strategy: <b>Missing Key Fallback Assertion</b> &bull; <b>Asymmetric Token Verification</b>

<span class="term-prompt">❯ pytest tests/test_deployproof_healed.py</span>
============================= test session starts =============================
tests/test_deployproof_healed.py::test_kill_verify_roles_line_14 <span class="term-success">PASSED</span> [ 50%]
tests/test_deployproof_healed.py::test_kill_inspect_symlink_line_108 <span class="term-success">PASSED</span> [100%]
============================== <span class="term-success">2 passed in 0.08s</span> ==============================
`,
  interactive: `
<span class="term-prompt">❯ deployproof check --interactive</span>
DeployProof: 42/44 mutants killed (95.4%). 2 surviving mutants found.

====================================================================
🔧 DeployProof Interactive Quick-Fix Mode (2 fixable mutant(s) found)
====================================================================

[?] Fix 1/2: src/auth.py:14
    Mutation : Replace dictionary .get() default fallback
    Strategy : Missing Key Fallback Assertion
    ------------------------------------------------------------
    | def test_kill_verify_roles_line_14():
    |     from auth import verify_roles
    |     assert verify_roles({"user": "admin"}) is not None
    ------------------------------------------------------------
    Apply to 'tests/test_auth.py'? [Y/n/q/all] (default: Y): <span class="term-prompt">y</span>
    <span class="term-success">[+] Appended 'test_kill_verify_roles_line_14' to tests/test_auth.py!</span>

[?] Fix 2/2: src/symlinks.py:108
    Apply to 'tests/test_symlinks.py'? [Y/n/q/all] (default: Y): <span class="term-prompt">y</span>
    <span class="term-success">[+] Appended 'test_kill_inspect_symlink_line_108' to tests/test_symlinks.py!</span>

====================================================================
<span class="term-success">🎉 Applied 2 self-healing test(s)! Mutation Score: 100.0% (44/44 killed)</span>
`,
  init: `
<span class="term-prompt">❯ deployproof init</span>
DeployProof: Initializing in /home/user/projects/my-api...

  <span class="term-success">[+]</span> Created configuration file: <b>pyproject.toml</b> ([tool.deployproof] section)
  <span class="term-success">[+]</span> Installed deterministic pre-push hook: <b>.git/hooks/pre-push</b>

🚀 <b>DeployProof is now active!</b>
   Every 'git push' will automatically verify the 7 quality and security gates.
`
};

function initTerminalTabs() {
  const tabs = document.querySelectorAll('.term-tab');
  const body = document.getElementById('terminal-content');
  if (!body) return;

  body.innerHTML = terminalScenarios.check.trim();

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const scenario = tab.getAttribute('data-scenario');
      body.innerHTML = (terminalScenarios[scenario] || '').trim();
    });
  });
}

/* ==========================================================================
   3. Interactive Gate Explorer Widget (LangGraph / Mintlify Style)
   ========================================================================== */
const gateExplorerData = {
  "1": {
    title: "Gate 1: In-Memory AST Schemata Mutation Testing",
    badge: "10x Faster • Zero Disk I/O",
    desc: "Compiles all AST mutants into a unified conditional AST tree in warm Python memory. Mutants switch instantly during execution via environment variables without creating or writing single files to disk.",
    code: `# How DeployProof injects all mutants in warm Python memory:
def calculate_discount(price: float, is_vip: bool) -> float:
    # Mutant 1: Relational boundary inverted (< vs <=)
    if os.environ.get("__DEPLOYPROOF_MUTANT__") == "1":
        if price < 100.0: return 0.0
    # Mutant 2: Boolean flag mutated (is_vip inverted)
    elif os.environ.get("__DEPLOYPROOF_MUTANT__") == "2":
        if not is_vip: return price * 0.2
    # Unmutated Production Code:
    if price <= 100.0:
        return 0.0
    return price * 0.15 if is_vip else price * 0.05`
  },
  "2": {
    title: "Gate 2: Actionable Self-Healing Test Synthesizer",
    badge: "Automated pytest Generation",
    desc: "When a mutant survives because a test suite is missing boundary checks or dictionary default fallbacks, DeployProof synthesizes ready-to-run pytest code that eliminates the blind spot.",
    code: `# Automatically Synthesized by DeployProof (--heal-tests):
import pytest
from payment_gateway import calculate_discount

def test_kill_mutant_discount_boundary_line_12():
    """Synthesized to kill mutant: Relational inverted at boundary 100.0"""
    assert calculate_discount(100.0, is_vip=False) == 0.0
    assert calculate_discount(100.01, is_vip=False) > 0.0`
  },
  "3": {
    title: "Gate 3: AST OWASP Top 10 SAST Scanner",
    badge: "AST Syntax Tree Pattern Matching",
    desc: "Inspects newly modified code for critical OWASP security flaws like SQL injections, arbitrary code execution with shell=True, and unsafe YAML/pickle deserialization.",
    code: `# Detected Vulnerability:
cursor.execute("SELECT * FROM users WHERE id = '%s'" % user_id)

# DeployProof AST Detection:
# ❌ SAST Finding: Unsanitized SQL query construction (CWE-89)
# Fix: Use parameterized queries: cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`
  },
  "4": {
    title: "Gate 4: Secrets & 50-Commit Git History Scanner",
    badge: "Shannon Entropy (≥ 3.8) + API Regex",
    desc: "Scans working tree changes and the last 50 commits to ensure developers or AI coding assistants never leak OpenAI, Anthropic, AWS, Stripe, or GitHub API keys.",
    code: `# Leaked Secret Detected across Git History:
OPENAI_API_KEY = "sk-proj-98fbc8a7e02947192837461928374619"

# DeployProof Defense:
# ❌ Gate 4 Block: High-entropy secret key detected (Shannon Entropy: 4.31)
# Push aborted. Key redacted in console output.`
  },
  "5": {
    title: "Gate 5: OSV CVE & Slopsquatting Defense",
    badge: "PyPI JSON API + OSV Database",
    desc: "Detects supply-chain attacks, vulnerable dependencies with known CVEs, and hallucinated package names invented by LLMs before pip install occurs in production.",
    code: `# Dependency Manifest Verification:
# requirements.txt:
langchain-openai-ultra==0.1.0  <-- Hallucinated LLM package!

# DeployProof Defense:
# ❌ HTTP 404 on PyPI registry. Flagged HIGH RISK Slopsquatting attempt.`
  },
  "6": {
    title: "Gate 6: CWE-61 Symlink Sandbox Escape Gate",
    badge: "Directory Traversal Protection",
    desc: "Resolves all filesystem symlinks in the repository to guarantee no pointer breaks outside the workspace root (neutralizing GhostApproval traversal exploits).",
    code: `# Malicious Symlink:
ln -s ../../../etc/shadow ./config/app_config.json

# DeployProof Defense:
# ❌ CWE-61 Path Traversal Escape Detected: symlink target escapes repository root.`
  },
  "7": {
    title: "Gate 7: Control Flow & Swallowed Exceptions Gate",
    badge: "CFG Reachability & Mock Leaks",
    desc: "Scans for blanket 'except Exception: pass' blocks that silently swallow runtime crashes, unreachable dead code, and mock leaks that mask broken implementations.",
    code: `# Swallowed Error Anti-Pattern:
try:
    process_payment(order)
except Exception:
    pass  # ❌ Critical Error Silently Swallowed!

# DeployProof Defense:
# ❌ Control Flow Gate: Broad exception swallowed without re-raise or logging.`
  }
};

function initGateExplorer() {
  const display = document.getElementById('explorer-display-area');
  const buttons = document.querySelectorAll('.explorer-btn');
  if (!display || !buttons.length) return;

  function renderGate(gateId) {
    const data = gateExplorerData[gateId] || gateExplorerData["1"];
    display.innerHTML = `
      <div class="explorer-card">
        <div class="explorer-header">
          <div>
            <h3 class="explorer-title">${data.title}</h3>
            <span class="hero-pill" style="margin: 0.4rem 0 0 0; padding: 0.2rem 0.6rem; font-size: 0.76rem;">${data.badge}</span>
          </div>
        </div>
        <p style="color: var(--text-secondary); margin: 1rem 0; font-size: 0.94rem;">${data.desc}</p>
        <div class="code-box" style="margin-top: 0.75rem;">
          <div class="code-header"><span>AST & VERIFICATION ENGINE PREVIEW</span><button class="copy-btn" data-clipboard-text="${data.code.replace(/"/g, '&quot;')}">Copy</button></div>
          <div class="code-body"><pre><code>${escapeHtml(data.code)}</code></pre></div>
        </div>
      </div>
    `;
    initCopyButtons();
  }

  renderGate("1");

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const gateId = btn.getAttribute('data-gate');
      renderGate(gateId);
    });
  });
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* ==========================================================================
   4. Copy to Clipboard Handlers
   ========================================================================== */
function initCopyButtons() {
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.onclick = async () => {
      const textToCopy = btn.getAttribute('data-clipboard-text') || '';
      if (!textToCopy) return;

      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalText = btn.textContent;
        btn.textContent = '✓ Copied!';
        btn.style.color = 'var(--accent-emerald)';
        btn.style.borderColor = 'var(--accent-emerald)';
        
        setTimeout(() => {
          btn.textContent = originalText;
          btn.style.color = '';
          btn.style.borderColor = '';
        }, 2000);
      } catch (err) {
        console.error('Failed to copy: ', err);
      }
    };
  });
}

/* ==========================================================================
   5. Client-Side Search (Ctrl+K)
   ========================================================================== */
const searchIndex = [
  { title: "Introduction & Overview", desc: "What is DeployProof, local privacy, and zero telemetry guarantee.", anchor: "#introduction" },
  { title: "Why 100% Line Coverage Lies", desc: "Understanding why line coverage misses broken assertions and subtle logic bugs.", anchor: "#why-coverage-lies" },
  { title: "Interactive Gate Explorer", desc: "Simulate and inspect all 7 verification gates.", anchor: "#interactive-gate-explorer" },
  { title: "Gate 1: In-Memory Mutation Testing", desc: "Compile AST mutants into warm Python memory with zero disk writes.", anchor: "#gate-1" },
  { title: "Gate 2: Self-Healing Test Synthesizer", desc: "Automatically generate pytest test cases for surviving mutants.", anchor: "#gate-2" },
  { title: "Gate 3: AST OWASP Top 10 SAST", desc: "SQL injection, command execution with shell=True, unsafe deserialization.", anchor: "#gate-3" },
  { title: "Gate 4: Secrets & Git History Scanner", desc: "Shannon entropy and 50-commit git traversal for leaked API keys.", anchor: "#gate-4" },
  { title: "Gate 5: OSV CVE & Slopsquatting", desc: "Vulnerability CVE scanning and hallucinated PyPI package protection.", anchor: "#gate-5" },
  { title: "Gate 6: Symlink Sandbox Gate", desc: "Directory traversal and CWE-61 repository containment verification.", anchor: "#gate-6" },
  { title: "Gate 7: Control Flow & Mocks", desc: "Swallowed exceptions, except Exception pass, and mock leakage detection.", anchor: "#gate-7" },
  { title: "2-Minute Quickstart", desc: "Install with pipx and run your first pre-push verification check.", anchor: "#quickstart" },
  { title: "Interactive Quick-Fix Mode (-i)", desc: "Prompt and apply self-healing tests directly inside your terminal.", anchor: "#interactive-mode" },
  { title: "GitHub Actions Workflow Recipe", desc: "Pull request inline annotations and visual Markdown step summaries.", anchor: "#github-actions" },
  { title: "Pre-Commit Framework Integration", desc: "Set up .pre-commit-config.yaml with deployproof-check.", anchor: "#pre-commit" },
  { title: "Configuration (pyproject.toml)", desc: "Standard PEP 518 [tool.deployproof] settings and threshold options.", anchor: "#configuration" },
  { title: "CLI Reference & Flags", desc: "Complete command line flags: --full-repo, --workers, --heal-tests, --json.", anchor: "#cli-reference" },
  { title: "Architecture & Performance Benchmarks", desc: "Why DeployProof is 10x faster than traditional mutation testing tools.", anchor: "#architecture" },
  { title: "FAQ & Troubleshooting", desc: "Common questions regarding network telemetry and multi-core scaling.", anchor: "#faq" }
];

function initSearch() {
  const trigger = document.getElementById('search-trigger');
  const modal = document.getElementById('search-modal');
  const input = document.getElementById('search-input');
  const results = document.getElementById('search-results');

  if (!modal || !input || !results) return;

  function openSearch() {
    modal.classList.add('open');
    input.value = '';
    renderSearchResults('');
    setTimeout(() => input.focus(), 50);
  }

  function closeSearch() {
    modal.classList.remove('open');
  }

  if (trigger) {
    trigger.addEventListener('click', openSearch);
  }

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      modal.classList.contains('open') ? closeSearch() : openSearch();
    }
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      closeSearch();
    }
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeSearch();
  });

  input.addEventListener('input', (e) => {
    renderSearchResults(e.target.value.toLowerCase().trim());
  });

  function renderSearchResults(query) {
    results.innerHTML = '';
    const filtered = searchIndex.filter(item => 
      !query || item.title.toLowerCase().includes(query) || item.desc.toLowerCase().includes(query)
    );

    if (!filtered.length) {
      results.innerHTML = `<li style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No results found for "${escapeHtml(query)}"</li>`;
      return;
    }

    filtered.forEach(item => {
      const li = document.createElement('li');
      li.className = 'search-result-item';
      li.innerHTML = `
        <div class="search-res-title">${item.title}</div>
        <div class="search-res-desc">${item.desc}</div>
      `;
      li.addEventListener('click', () => {
        closeSearch();
        window.location.hash = item.anchor;
      });
      results.appendChild(li);
    });
  }
}

/* ==========================================================================
   6. Dynamic Scrollspy for Left & Right Navigation
   ========================================================================== */
function initScrollspy() {
  const sections = document.querySelectorAll('.doc-section, .hero-section');
  const sidebarLinks = document.querySelectorAll('.sidebar-link');
  const tocLinks = document.querySelectorAll('.toc-link');

  window.addEventListener('scroll', () => {
    let currentId = '';
    const scrollPos = window.scrollY + 120;

    sections.forEach(sec => {
      const top = sec.offsetTop;
      const height = sec.offsetHeight;
      if (scrollPos >= top && scrollPos < top + height) {
        currentId = sec.getAttribute('id');
      }
    });

    if (!currentId) return;

    sidebarLinks.forEach(link => {
      if (link.getAttribute('href') === `#${currentId}`) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    tocLinks.forEach(link => {
      if (link.getAttribute('href') === `#${currentId}`) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });
  });
}
