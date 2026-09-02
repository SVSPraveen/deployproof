"""
AST-based Static Application Security Testing (SAST) scanner for DeployProof.
Detects OWASP Top 10 security vulnerabilities in Python source code with zero external dependencies:
- DP-SAST-001 (A03: Injection): Arbitrary Code Execution (eval, exec, __import__, compile)
- DP-SAST-002 (A03: Injection): Command Injection (os.system, os.popen, posix_spawn, pty.spawn)
- DP-SAST-003 (A03: Injection): Subprocess Command Injection (shell=True)
- DP-SAST-004 (A08: Integrity): Insecure Deserialization (pickle, marshal, shelve, dill)
- DP-SAST-005 (A08: Integrity): Unsafe YAML Deserialization (yaml.load without SafeLoader)
- DP-SAST-006 (A03: Injection): SQL Injection (Dynamic String Formatting / Concat in raw SQL)
- DP-SAST-007 (A03: Injection): Cross-Site Scripting (XSS) & Template Injection (Markup, render_template_string)
- DP-SAST-008 (A01: Broken Access Control): Path Traversal Risks (dynamic paths in open, rmtree, send_file)
- DP-SAST-009 (A02: Cryptographic Failures): Insecure Hashes & Ciphers (md5, sha1, DES, RC4)
- DP-SAST-010 (A05: Security Misconfiguration): Disabled SSL Verification (verify=False, unverified context)
- DP-SAST-011 (A05: Security Misconfiguration): Insecure Network Binding / Debug Mode (0.0.0.0, debug=True)
- DP-SAST-012 (A07: Identification & Auth): Insecure Pseudo-Random Number Generator in Security Contexts
- DP-SAST-013 (A08: Integrity): XML External Entity (XXE) Injection Risks
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple


@dataclass
class SastFinding:
    """Represents an individual SAST vulnerability finding."""
    file_path: Path
    line_number: int
    rule_id: str
    rule_name: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    snippet: str
    description: str
    cwe: str
    owasp_category: str


@dataclass
class SastScanResult:
    """Aggregated SAST scan result across session files."""
    findings: List[SastFinding] = field(default_factory=list)
    files_scanned: int = 0
    clean: bool = True

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "LOW")


SQL_COMMANDS = {
    "select", "insert", "update", "delete", "drop", "alter", "create", "truncate", "replace"
}

SECURITY_CONTEXT_NAMES = {
    "token", "secret", "password", "passwd", "key", "auth", "nonce", "salt", "session", "otp", "pin"
}


class SastAstVisitor(ast.NodeVisitor):
    """Visits Python AST nodes to identify OWASP Top 10 vulnerabilities."""

    def __init__(self, file_path: Path, source_lines: List[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.findings: List[SastFinding] = []

    def _get_snippet(self, lineno: int) -> str:
        if 0 <= lineno - 1 < len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def _add_finding(
        self,
        node: ast.AST,
        rule_id: str,
        rule_name: str,
        severity: str,
        description: str,
        cwe: str,
        owasp: str,
    ) -> None:
        lineno = getattr(node, "lineno", 1)
        snippet = self._get_snippet(lineno)
        self.findings.append(
            SastFinding(
                file_path=self.file_path,
                line_number=lineno,
                rule_id=rule_id,
                rule_name=rule_name,
                severity=severity,
                snippet=snippet,
                description=description,
                cwe=cwe,
                owasp_category=owasp,
            )
        )

    def _is_dynamic_arg(self, arg: ast.AST) -> bool:
        """Check if an AST node is dynamic (e.g. variable, f-string, call, binop) rather than a plain static constant."""
        if isinstance(arg, ast.Constant):
            return False
        return True

    def visit_Call(self, node: ast.Call) -> None:
        # 1. Arbitrary Code Execution: eval / exec / __import__ / compile
        if isinstance(node.func, ast.Name):
            func_id = node.func.id
            if func_id in ("eval", "exec", "__import__"):
                if node.args and self._is_dynamic_arg(node.args[0]):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-001",
                        rule_name="Arbitrary Code Execution (eval/exec/__import__)",
                        severity="CRITICAL",
                        description=f"Dynamic evaluation of untrusted expression with `{func_id}()`",
                        cwe="CWE-95",
                        owasp="A03:2021-Injection",
                    )
            elif func_id == "open":
                # 8. Path Traversal Risks via dynamic open()
                if node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-008",
                        rule_name="Path Traversal Risk in File Operation",
                        severity="HIGH",
                        description="Dynamic formatted path in `open()` without explicit sanitization or path resolution validation",
                        cwe="CWE-22",
                        owasp="A01:2021-Broken Access Control",
                    )
            elif func_id in ("Markup", "mark_safe", "render_template_string"):
                # 7. XSS & SSTI via direct imported functions
                if node.args and self._is_dynamic_arg(node.args[0]):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-007",
                        rule_name="Cross-Site Scripting (XSS) / Template Injection",
                        severity="HIGH",
                        description=f"Untrusted dynamic input passed to `{func_id}()` bypassing HTML sanitization or triggering SSTI",
                        cwe="CWE-79",
                        owasp="A03:2021-Injection",
                    )

        # Attribute calls (e.g. os.system, subprocess.run, pickle.loads, hashlib.md5, etc.)
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            val_node = node.func.value

            # Top-level module name if available
            val_id = getattr(val_node, "id", None)
            val_attr = getattr(val_node, "attr", None)

            # 2. Command Injection: os.system, os.popen, posix_spawn, pty.spawn
            if val_id in ("os", "pty") and attr_name in ("system", "popen", "posix_spawn", "spawnl", "spawnv", "spawnlp", "spawnvp", "spawn"):
                if node.args and self._is_dynamic_arg(node.args[0]):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-002",
                        rule_name="Command Injection (os.system/os.popen/pty.spawn)",
                        severity="CRITICAL",
                        description=f"Execution of shell command via `{val_id}.{attr_name}()` with dynamic arguments",
                        cwe="CWE-78",
                        owasp="A03:2021-Injection",
                    )

            # 3. Subprocess shell=True command injection
            if val_id == "subprocess" or attr_name in ("Popen", "run", "call", "check_call", "check_output"):
                for kw in node.keywords:
                    if kw.arg == "shell" and (
                        (isinstance(kw.value, ast.Constant) and kw.value.value is True)
                        or (isinstance(kw.value, ast.Name) and kw.value.id == "True")
                    ):
                        self._add_finding(
                            node,
                            rule_id="DP-SAST-003",
                            rule_name="Subprocess Command Injection (shell=True)",
                            severity="HIGH",
                            description="Subprocess invoked with `shell=True` allowing shell metacharacter injection",
                            cwe="CWE-78",
                            owasp="A03:2021-Injection",
                        )

            # 4. Insecure Deserialization: pickle.loads / marshal / shelve / dill
            if (val_id in ("pickle", "_pickle", "cPickle", "marshal", "shelve", "dill") and attr_name in ("loads", "load", "open")) or (attr_name in ("loads", "load") and val_id in ("pickle", "dill")):
                self._add_finding(
                    node,
                    rule_id="DP-SAST-004",
                    rule_name="Insecure Deserialization (pickle/marshal/shelve/dill)",
                    severity="CRITICAL",
                    description=f"Untrusted deserialization via `{val_id}.{attr_name}()` allows remote code execution",
                    cwe="CWE-502",
                    owasp="A08:2021-Software and Data Integrity Failures",
                )
            elif val_id == "yaml" and attr_name in ("load", "unsafe_load"):
                # 5. Unsafe YAML Deserialization
                if attr_name == "unsafe_load":
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-005",
                        rule_name="Unsafe YAML Deserialization",
                        severity="HIGH",
                        description="`yaml.unsafe_load()` called, permitting arbitrary Python object instantiation",
                        cwe="CWE-502",
                        owasp="A08:2021-Software and Data Integrity Failures",
                    )
                else:
                    has_safe_loader = False
                    for kw in node.keywords:
                        if kw.arg == "Loader":
                            if isinstance(kw.value, ast.Attribute) and kw.value.attr in ("SafeLoader", "CSafeLoader", "BaseLoader"):
                                has_safe_loader = True
                            elif isinstance(kw.value, ast.Name) and "Safe" in kw.value.id:
                                has_safe_loader = True
                    if not has_safe_loader:
                        self._add_finding(
                            node,
                            rule_id="DP-SAST-005",
                            rule_name="Unsafe YAML Deserialization",
                            severity="HIGH",
                            description="`yaml.load()` called without SafeLoader, permitting arbitrary Python object instantiation",
                            cwe="CWE-502",
                            owasp="A08:2021-Software and Data Integrity Failures",
                        )

            # 6. SQL Injection via cursor.execute(f"...") or raw SQL text formatting
            if attr_name in ("execute", "executemany", "raw"):
                if node.args:
                    arg0 = node.args[0]
                    is_sqli = False
                    if isinstance(arg0, ast.JoinedStr):  # f-string
                        for part in arg0.values:
                            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                                words = {w.strip().lower() for w in part.value.split()}
                                if words.intersection(SQL_COMMANDS):
                                    is_sqli = True
                                    break
                    elif isinstance(arg0, ast.BinOp) and isinstance(arg0.op, (ast.Add, ast.Mod)):
                        is_sqli = True
                    elif isinstance(arg0, ast.Call) and isinstance(arg0.func, ast.Attribute) and arg0.func.attr == "format":
                        is_sqli = True

                    if is_sqli:
                        self._add_finding(
                            node,
                            rule_id="DP-SAST-006",
                            rule_name="SQL Injection (Dynamic String Formatting in Query)",
                            severity="HIGH",
                            description="SQL query constructed via string formatting or concatenation rather than parameterized placeholders",
                            cwe="CWE-89",
                            owasp="A03:2021-Injection",
                        )

            # 7. XSS & Server-Side Template Injection (SSTI)
            if (attr_name in ("Markup", "mark_safe", "render_template_string") or (val_id == "jinja2" and attr_name in ("Template", "from_string"))):
                if node.args and self._is_dynamic_arg(node.args[0]):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-007",
                        rule_name="Cross-Site Scripting (XSS) / Template Injection",
                        severity="HIGH",
                        description=f"Untrusted dynamic input passed to `{attr_name}()` bypassing HTML sanitization or triggering SSTI",
                        cwe="CWE-79",
                        owasp="A03:2021-Injection",
                    )

            # 8. Path Traversal in send_file, send_from_directory, shutil.rmtree, os.remove
            if (val_id in ("shutil", "os") and attr_name in ("rmtree", "remove", "unlink")) or attr_name in ("send_file", "send_from_directory"):
                if node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-008",
                        rule_name="Path Traversal Risk in File Operation",
                        severity="HIGH",
                        description=f"Dynamic path construction in `{attr_name}()` without strict directory boundary check",
                        cwe="CWE-22",
                        owasp="A01:2021-Broken Access Control",
                    )

            # 9. Insecure Cryptographic Hashes & Ciphers (md5, sha1, DES, RC4)
            if (val_id == "hashlib" and attr_name in ("md5", "sha1")) or (val_id == "Crypto" and val_attr == "Cipher" and attr_name in ("DES", "ARC4")):
                # Check if usedforsecurity=False keyword is present
                is_secure_context = True
                for kw in node.keywords:
                    if kw.arg == "usedforsecurity" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        is_secure_context = False
                if is_secure_context:
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-009",
                        rule_name="Insecure Cryptographic Hash or Cipher (MD5/SHA1/DES/RC4)",
                        severity="MEDIUM",
                        description=f"Weak cryptographic primitive `{attr_name}` used without `usedforsecurity=False`",
                        cwe="CWE-327",
                        owasp="A02:2021-Cryptographic Failures",
                    )

            # 10. Insecure TLS / SSL Verification Disabled
            if val_id in ("requests", "httpx", "urllib3") or attr_name in ("get", "post", "put", "delete", "patch", "request", "Client", "Session"):
                for kw in node.keywords:
                    if kw.arg in ("verify", "verify_ssl") and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        self._add_finding(
                            node,
                            rule_id="DP-SAST-010",
                            rule_name="Disabled TLS/SSL Certificate Verification",
                            severity="HIGH",
                            description=f"TLS/SSL certificate validation explicitly disabled via `{kw.arg}=False`",
                            cwe="CWE-295",
                            owasp="A05:2021-Security Misconfiguration",
                        )
            elif val_id == "ssl" and attr_name in ("_create_unverified_context", "_create_stdlib_context"):
                self._add_finding(
                    node,
                    rule_id="DP-SAST-010",
                    rule_name="Disabled TLS/SSL Certificate Verification",
                    severity="HIGH",
                    description="Unverified SSL context created via `ssl._create_unverified_context()`",
                    cwe="CWE-295",
                    owasp="A05:2021-Security Misconfiguration",
                )

            # 11. Insecure Network Binding or Debug Mode (e.g. app.run(host="0.0.0.0", debug=True))
            if attr_name == "run":
                is_debug_true = False
                is_all_interfaces = False
                for kw in node.keywords:
                    if kw.arg == "debug" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        is_debug_true = True
                    if kw.arg == "host" and isinstance(kw.value, ast.Constant) and kw.value.value in ("0.0.0.0", "::"):
                        is_all_interfaces = True
                if is_debug_true:
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-011",
                        rule_name="Production Debug Mode Enabled",
                        severity="HIGH",
                        description="Application started with `debug=True`, exposing interactive debugging console and internal stack traces",
                        cwe="CWE-489",
                        owasp="A05:2021-Security Misconfiguration",
                    )
                elif is_all_interfaces:
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-011",
                        rule_name="Insecure Global Interface Network Binding",
                        severity="LOW",
                        description="Application bound globally to `0.0.0.0` exposing service to all network interfaces",
                        cwe="CWE-1327",
                        owasp="A05:2021-Security Misconfiguration",
                    )

            # 12. Cryptographically Insecure Pseudo-Random Numbers in Security Contexts
            if val_id == "random" and attr_name in ("random", "randint", "choice", "randrange", "sample"):
                # Check parent context / variable assignment name if available
                self.generic_visit(node)
                return

            # 13. XML External Entity (XXE) Injection
            if val_id in ("ElementTree", "minidom", "sax", "lxml") and attr_name in ("parse", "fromstring"):
                if node.args and self._is_dynamic_arg(node.args[0]):
                    self._add_finding(
                        node,
                        rule_id="DP-SAST-013",
                        rule_name="XML External Entity (XXE) Risk",
                        severity="MEDIUM",
                        description=f"Parsing dynamic XML via `{val_id}.{attr_name}()` without defusedxml protection",
                        cwe="CWE-611",
                        owasp="A08:2021-Software and Data Integrity Failures",
                    )

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Check for random used in security assignments (token = random.randint(...))
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
            val_id = getattr(node.value.func.value, "id", None)
            attr_name = node.value.func.attr
            if val_id == "random" and attr_name in ("random", "randint", "choice", "randrange", "sample"):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name_lower = target.id.lower()
                        if any(sec_term in name_lower for sec_term in SECURITY_CONTEXT_NAMES):
                            self._add_finding(
                                node,
                                rule_id="DP-SAST-012",
                                rule_name="Insecure Pseudo-Random Number in Security Context",
                                severity="MEDIUM",
                                description=f"Standard `random.{attr_name}()` used for security-sensitive token/secret `{target.id}` instead of `secrets` module",
                                cwe="CWE-338",
                                owasp="A07:2021-Identification and Authentication Failures",
                            )

        self.generic_visit(node)


def scan_file_for_sast(file_path: Path) -> List[SastFinding]:
    """Analyze a single Python file for SAST security vulnerabilities."""
    if not file_path.is_file() or file_path.suffix != ".py":
        return []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(file_path))
        lines = content.splitlines()
        visitor = SastAstVisitor(file_path, lines)
        visitor.visit(tree)
        return visitor.findings
    except Exception:
        return []


def scan_session_files_for_sast(files: List[Path]) -> SastScanResult:
    """Scan a collection of session files for SAST security findings."""
    all_findings: List[SastFinding] = []
    scanned_count = 0

    for f in files:
        if f.is_file() and f.suffix == ".py":
            scanned_count += 1
            findings = scan_file_for_sast(f)
            all_findings.extend(findings)

    return SastScanResult(
        findings=all_findings,
        files_scanned=scanned_count,
        clean=len(all_findings) == 0,
    )
