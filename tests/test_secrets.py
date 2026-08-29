"""Tests for DeployProof secrets and credential scanner."""

import tempfile
from pathlib import Path
from deployproof.secrets import (
    calculate_shannon_entropy,
    is_placeholder,
    redact_secret,
    scan_file_for_secrets,
    scan_session_files_for_secrets,
)


def test_redact_secret():
    """Verify secrets are redacted displaying only first 2 and last 2 characters."""
    assert redact_secret("sk-proj-1234567890abcdef") == "sk****************ef"
    assert redact_secret("AKIAIOSFODNN7EXAMPLE") == "AK****************LE"
    assert redact_secret("short") == "sh****************rt"
    assert redact_secret("abc") == "****"


def test_shannon_entropy():
    """Verify entropy calculations."""
    assert calculate_shannon_entropy("aaaaaaaaaaaaaaaa") < 1.0
    # High entropy random base64 string
    high_ent = calculate_shannon_entropy("9kL#pQ2$vN8@zW1!xY5&")
    assert high_ent > 4.0


def test_placeholder_filtering():
    """Verify placeholder keys are ignored."""
    assert is_placeholder("your-api-key-here") is True
    assert is_placeholder("MY_SECRET_KEY_PLACEHOLDER") is True
    assert is_placeholder("test_token_123") is True
    assert is_placeholder("ak_live_999988887777") is False


def test_scan_openai_and_aws_keys():
    """Verify scanning detects OpenAI and AWS keys and redacts them."""
    content = '''
OPENAI_KEY = "sk-proj-9A8b7c6D5e4F3g2H1i0JkLmNoPqRsTuVwXyZ"
AWS_KEY = "AKIA1234567890ABCDEF"
SAFE_TEXT = "This is normal code"
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "config.py"
        f.write_text(content, encoding="utf-8")
        findings = scan_file_for_secrets(f)

        assert len(findings) == 2
        rules = [find.rule_name for find in findings]
        assert "OpenAI / Anthropic API Key" in rules
        assert "AWS Access Key ID" in rules

        for find in findings:
            assert "sk-proj-9A8b" not in find.redacted_value
            assert find.redacted_value.startswith("sk") or find.redacted_value.startswith("AK")
            assert "****************" in find.redacted_value


def test_scan_tracked_env_file():
    """Verify tracked .env files are flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("DATABASE_URL=postgres://localhost\n", encoding="utf-8")
        findings = scan_file_for_secrets(env_file)

        assert len(findings) >= 1
        assert any(f.rule_name == "Tracked Environment File" for f in findings)


def test_scan_high_entropy_assignment():
    """Verify high-entropy secret assignments are flagged while placeholders are ignored."""
    content = '''
# Real secret
api_secret = "9xK#mQ2$vN8@zW1!aB7&cE3*gH5)"
# Placeholder (should NOT be flagged)
api_token = "your-api-token-placeholder-here"
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "credentials.py"
        f.write_text(content, encoding="utf-8")
        findings = scan_file_for_secrets(f)

        assert len(findings) == 1
        assert findings[0].rule_name == "High-Entropy Credential Assignment"
        assert findings[0].line_number == 3


def test_scan_json_and_yaml_files():
    """Verify secrets scanning works across json and yaml files."""
    json_content = '{"github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz"}'
    yaml_content = 'slack_token: xoxb-123456789012-345678901234-abcdefghijklmnopqrstuvwx'

    with tempfile.TemporaryDirectory() as tmpdir:
        jf = Path(tmpdir) / "auth.json"
        jf.write_text(json_content, encoding="utf-8")
        yf = Path(tmpdir) / "config.yaml"
        yf.write_text(yaml_content, encoding="utf-8")

        res = scan_session_files_for_secrets([jf, yf])
        assert res.files_scanned == 2
        assert len(res.findings) == 2
        rules = [f.rule_name for f in res.findings]
        assert "GitHub Token" in rules
        assert "Slack Token" in rules


def test_scan_unquoted_env_secrets():
    """Verify scanner catches individual unquoted secrets inside .env files beyond the tracked file warning."""
    env_content = '''# Sample production environment variables
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
DB_PASSWORD=v3ry_s3cr3t_p@ssw0rd_1234567890
STRIPE_SECRET_KEY=sk_live_51AbCdEfGhIjKlMnOpQrStUvWxYz1234567890
SAFE_SETTING=production
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env.production"
        env_file.write_text(env_content, encoding="utf-8")

        findings = scan_file_for_secrets(env_file)
        # Expected: 1 tracked env file finding + 3 secret value findings = 4 total
        assert len(findings) == 4

        rules = {f.rule_name: f for f in findings}
        assert "Tracked Environment File" in rules
        assert "AWS Secret Access Key" in rules
        assert "High-Entropy Credential Assignment" in rules
        assert "Stripe Secret Key" in rules

        # Verify line numbers and secret contents
        aws_finding = rules["AWS Secret Access Key"]
        assert aws_finding.line_number == 2
        assert aws_finding.redacted_value.startswith("wJ") and aws_finding.redacted_value.endswith("EY")

        pwd_finding = rules["High-Entropy Credential Assignment"]
        assert pwd_finding.line_number == 3
        assert pwd_finding.redacted_value.startswith("v3") and pwd_finding.redacted_value.endswith("90")

        stripe_finding = rules["Stripe Secret Key"]
        assert stripe_finding.line_number == 4
        assert stripe_finding.redacted_value.startswith("sk") and stripe_finding.redacted_value.endswith("90")


def test_false_positive_patterns_ignored():
    """Verify that identifiers like pass_arg, schema fields, and ContextVar tokens are not falsely flagged."""
    content = '''
# 1. Parameter / argument names containing pass_
pass_script_info = click.make_pass_decorator(ScriptInfo, ensure=True)
pass_arg = _PassArg.from_obj(normal_func)
pass_original = validator_kwargs.get("pass_original", False)

# 2. Schema field definitions
password = fields.Str(load_only=True)
password = fields.String(validate=lambda x: x == "password")
password = fields.String(validate=[must_have_number, validate_length])

# 3. ContextVar token objects and token collections
self.token = _CURRENT_CONTEXT.set(self.context)
self._cv_token: contextvars.Token[AppContext] | None = None
tokens = list(environment.lex(environment.preprocess(source)))
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "sample_code.py"
        f.write_text(content, encoding="utf-8")
        findings = scan_file_for_secrets(f)
        assert len(findings) == 0


