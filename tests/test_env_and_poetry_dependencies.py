import os
import subprocess
from pathlib import Path
import pytest

from deployproof.diff import resolve_changed_session_files, is_ignored_path, IGNORED_DIRS
from deployproof.secrets import scan_session_files_for_secrets
from deployproof.dependencies import extract_all_new_dependencies, scan_dependencies


def test_env_file_not_ignored_and_scanned_for_secrets(tmp_path):
    """Bug #2: Verify .env file is NOT ignored by session_files and is caught by secrets scanner."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

    env_file = repo / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=sk-proj-realistickeylookingvalue1234567890ABCDEFG\nDB_PASSWORD=SuperSecretPass123!!\n",
        encoding="utf-8",
    )

    # Verify is_ignored_path does NOT ignore .env file
    assert not is_ignored_path(env_file, repo)

    session_files = resolve_changed_session_files(cwd=repo)
    assert any(f.name == ".env" for f in session_files), ".env file was ignored in session_files"

    sec_res = scan_session_files_for_secrets(session_files)
    assert len(sec_res.findings) >= 1
    rules = {f.rule_name for f in sec_res.findings}
    assert any("Environment File" in r or "OpenAI" in r or "API Key" in r for r in rules)


def test_env_directory_package_not_ignored(tmp_path):
    """Bug #3: Verify normal python package folder named 'env/' is NOT ignored."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

    env_pkg = repo / "env"
    env_pkg.mkdir()
    game_env = env_pkg / "game_env.py"
    game_env.write_text("class GameEnv:\n    pass\n", encoding="utf-8")

    # Verify is_ignored_path does NOT ignore normal env/ folder
    assert not is_ignored_path(game_env, repo)

    session_files = resolve_changed_session_files(cwd=repo)
    assert any(f.name == "game_env.py" for f in session_files), "env/game_env.py was wrongly ignored"


def test_poetry_dependencies_parsed(tmp_path):
    """Bug #4: Verify Poetry-style pyproject.toml dependencies are parsed."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.28.0"
another-fake-dep-7766 = "^2.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
dev-fake-pkg = ">=1.0"
""",
        encoding="utf-8",
    )

    deps = extract_all_new_dependencies([pyproject], root=tmp_path, full_repo=True)
    names = {d.name for d in deps}
    assert "requests" in names
    assert "another-fake-dep-7766" in names
    assert "pytest" in names
    assert "dev-fake-pkg" in names
    assert "python" not in names  # python constraint should be skipped


def test_poetry_lock_dependencies_parsed(tmp_path):
    """Verify lockfile parsing from poetry.lock with pinned versions and checksum hashes."""
    poetry_lock = tmp_path / "poetry.lock"
    poetry_lock.write_text(
        """
[[package]]
name = "fastapi"
version = "0.110.0"
description = "FastAPI framework"

[[package]]
name = "pydantic"
version = "2.6.4"
description = "Data validation using Python type annotations"
""",
        encoding="utf-8",
    )

    deps = extract_all_new_dependencies([poetry_lock], root=tmp_path, full_repo=True)
    names = {d.name for d in deps}
    assert "fastapi" in names
    assert "pydantic" in names


def test_pipfile_lock_dependencies_parsed(tmp_path):
    """Verify lockfile parsing from Pipfile.lock."""
    pipfile_lock = tmp_path / "Pipfile.lock"
    pipfile_lock.write_text(
        """{
    "_meta": {"hash": {"sha256": "abcdef"}},
    "default": {
        "httpx": {"hashes": ["sha256:123456"], "version": "==0.27.0"}
    },
    "develop": {
        "pytest-asyncio": {"hashes": ["sha256:789012"], "version": "==0.23.0"}
    }
}""",
        encoding="utf-8",
    )

    deps = extract_all_new_dependencies([pipfile_lock], root=tmp_path, full_repo=True)
    names = {d.name for d in deps}
    assert "httpx" in names
    assert "pytest-asyncio" in names


def test_requirements_with_sha256_hashes_parsed(tmp_path):
    """Verify requirements.txt with --hash=sha256:... flags is parsed cleanly."""
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(
        """urllib3==2.2.1 \\
    --hash=sha256:450b6ff2a6ce09cfd5e64e5244136a53c2d4307d464e6d92f23a995283ba768a
certifi==2024.2.2 --hash=sha256:dc383c07b76109f368f615ba4b77735205ce90e83515807a615633bc4d404b80
""",
        encoding="utf-8",
    )

    deps = extract_all_new_dependencies([reqs], root=tmp_path, full_repo=True)
    names = {d.name for d in deps}
    assert "urllib3" in names
    assert "certifi" in names

