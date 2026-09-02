"""
Comprehensive test suite for DeployProof SAST scanner (OWASP Top 10 Python vulnerabilities).
"""

import tempfile
from pathlib import Path
import pytest

from deployproof.sast import scan_file_for_sast, scan_session_files_for_sast


def test_sast_command_injection_detection(tmp_path: Path):
    """Verify detection of os.system, os.popen, and subprocess with shell=True."""
    f = tmp_path / "cmd_vuln.py"
    f.write_text("""import os, subprocess

def run_user_cmd(cmd_str):
    os.system(cmd_str)
    os.popen("echo " + cmd_str)
    subprocess.run(cmd_str, shell=True)
    subprocess.Popen(f"ls {cmd_str}", shell=True)
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) >= 4
    rule_ids = {f.rule_id for f in findings}
    assert "DP-SAST-002" in rule_ids  # os.system / os.popen
    assert "DP-SAST-003" in rule_ids  # subprocess shell=True


def test_sast_arbitrary_code_execution(tmp_path: Path):
    """Verify detection of eval() and exec() with dynamic arguments."""
    f = tmp_path / "code_exec.py"
    f.write_text("""def evaluate_expr(user_code):
    eval(user_code)
    exec(user_code)
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-001" for f in findings)
    assert all(f.severity == "CRITICAL" for f in findings)


def test_sast_insecure_deserialization(tmp_path: Path):
    """Verify detection of pickle.loads, marshal.loads, and yaml.load without SafeLoader."""
    f = tmp_path / "deserial_vuln.py"
    f.write_text("""import pickle, yaml, marshal

def parse_payload(raw_bytes, raw_yaml):
    obj1 = pickle.loads(raw_bytes)
    obj2 = marshal.loads(raw_bytes)
    obj3 = yaml.load(raw_yaml)  # unsafe
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 3
    rule_ids = {f.rule_id for f in findings}
    assert "DP-SAST-004" in rule_ids  # pickle / marshal
    assert "DP-SAST-005" in rule_ids  # unsafe yaml


def test_sast_sql_injection_detection(tmp_path: Path):
    """Verify detection of formatted strings and concatenations in raw SQL execution."""
    f = tmp_path / "db_vuln.py"
    f.write_text("""def get_user(cursor, username):
    cursor.execute(f"SELECT * FROM users WHERE name = '{username}'")
    cursor.execute("SELECT id FROM accounts WHERE name = " + username)
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-006" for f in findings)
    assert all(f.cwe == "CWE-89" for f in findings)


def test_sast_xss_and_template_injection(tmp_path: Path):
    """Verify detection of unescaped HTML Markup and render_template_string SSTI."""
    f = tmp_path / "xss_vuln.py"
    f.write_text("""from markupsafe import Markup
from flask import render_template_string

def render_html(user_input):
    safe_html = Markup(user_input)
    page = render_template_string(f"Hello {user_input}")
    return safe_html, page
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-007" for f in findings)
    assert all(f.cwe == "CWE-79" for f in findings)


def test_sast_path_traversal(tmp_path: Path):
    """Verify detection of dynamic unvalidated paths in file operations."""
    f = tmp_path / "path_vuln.py"
    f.write_text("""import shutil

def read_user_file(user_filename):
    with open(f"/data/{user_filename}") as fp:
        return fp.read()

def cleanup_user_dir(user_id):
    shutil.rmtree("/tmp/users/" + user_id)
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-008" for f in findings)
    assert all(f.cwe == "CWE-22" for f in findings)


def test_sast_insecure_crypto_and_hashes(tmp_path: Path):
    """Verify detection of weak cryptographic algorithms (MD5, SHA1)."""
    f = tmp_path / "crypto_vuln.py"
    f.write_text("""import hashlib

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def check_token(token):
    return hashlib.sha1(token.encode()).hexdigest()
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-009" for f in findings)
    assert all(f.cwe == "CWE-327" for f in findings)


def test_sast_disabled_tls_ssl(tmp_path: Path):
    """Verify detection of verify=False and unverified SSL contexts."""
    f = tmp_path / "tls_vuln.py"
    f.write_text("""import requests, ssl

def fetch_data(url):
    res = requests.get(url, verify=False)
    ctx = ssl._create_unverified_context()
    return res, ctx
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-010" for f in findings)
    assert all(f.cwe == "CWE-295" for f in findings)


def test_sast_debug_mode_and_global_binding(tmp_path: Path):
    """Verify detection of app.run(debug=True) and 0.0.0.0 global interface binding."""
    f = tmp_path / "app_vuln.py"
    f.write_text("""class App:
    def run(self, host="127.0.0.1", debug=False):
        pass

app = App()
app.run(host="0.0.0.0", debug=True)
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) >= 1
    rule_ids = {f.rule_id for f in findings}
    assert "DP-SAST-011" in rule_ids


def test_sast_insecure_randomness_in_security_contexts(tmp_path: Path):
    """Verify detection of random used for secret/token variables."""
    f = tmp_path / "random_vuln.py"
    f.write_text("""import random

def generate_auth_token():
    auth_token = random.randint(100000, 999999)
    session_secret = random.random()
    return auth_token, session_secret
""", encoding="utf-8")

    findings = scan_file_for_sast(f)
    assert len(findings) == 2
    assert all(f.rule_id == "DP-SAST-012" for f in findings)
    assert all(f.cwe == "CWE-338" for f in findings)


def test_sast_clean_code_not_flagged(tmp_path: Path):
    """Verify safe coding patterns produce zero false positive SAST findings."""
    f = tmp_path / "safe_code.py"
    f.write_text("""import subprocess, yaml, hashlib, secrets

def safe_math(a, b):
    return a + b

def safe_subprocess():
    subprocess.run(["ls", "-la"], check=True)

def safe_yaml(content):
    return yaml.load(content, Loader=yaml.SafeLoader)

def safe_sql(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

def safe_token():
    return secrets.token_hex(32)

def safe_checksum(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()
""", encoding="utf-8")

    res = scan_session_files_for_sast([f])
    assert res.clean is True
    assert len(res.findings) == 0
