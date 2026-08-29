"""Tests for dependency and import extractor (Piece 1)."""

import os
import subprocess
from pathlib import Path
from deployproof.dependencies import (
    ExtractedDependency,
    extract_all_new_dependencies,
    extract_new_imports_from_py_file,
    extract_new_manifest_dependencies,
    get_local_module_names,
    normalize_package_name,
)


def test_normalize_package_name():
    assert normalize_package_name("yaml") == "PyYAML"
    assert normalize_package_name("PIL") == "Pillow"
    assert normalize_package_name("cv2") == "opencv-python"
    assert normalize_package_name("requests") == "requests"
    assert normalize_package_name("fastapi") == "fastapi"


def test_extract_imports_filters_stdlib_and_local(tmp_path: Path):
    # Setup a mock repo structure
    root = tmp_path / "mock_repo"
    root.mkdir()
    (root / "my_local_pkg").mkdir()
    (root / "my_local_pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "local_helper.py").write_text("def help(): pass\n", encoding="utf-8")

    test_file = root / "app.py"
    test_file.write_text(
        """
import os
import sys
import json
from pathlib import Path
from typing import List, Optional

# Local imports
import local_helper
from my_local_pkg import something
from .relative_mod import relative_func
from ..parent_mod import parent_func

# External imports
import requests
import fastapi
from pydantic import BaseModel
import yaml
from PIL import Image
import hallucinated_pkg_12345
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    assert "local_helper" in local_modules
    assert "my_local_pkg" in local_modules

    extracted = extract_new_imports_from_py_file(
        test_file,
        root=root,
        local_modules=local_modules,
        base=None,
    )

    extracted_names = [d.name for d in extracted]

    # Stdlib should be filtered out
    assert "os" not in extracted_names
    assert "sys" not in extracted_names
    assert "json" not in extracted_names
    assert "pathlib" not in extracted_names
    assert "typing" not in extracted_names

    # Local modules should be filtered out
    assert "local_helper" not in extracted_names
    assert "my_local_pkg" not in extracted_names
    assert "relative_mod" not in extracted_names
    assert "parent_mod" not in extracted_names

    # External dependencies should be cleanly extracted and normalized
    assert "requests" in extracted_names
    assert "fastapi" in extracted_names
    assert "pydantic" in extracted_names
    assert "PyYAML" in extracted_names  # normalized from yaml
    assert "Pillow" in extracted_names  # normalized from PIL
    assert "hallucinated_pkg_12345" in extracted_names


def test_extract_manifest_requirements_txt(tmp_path: Path):
    root = tmp_path / "mock_repo"
    root.mkdir()
    req_file = root / "requirements.txt"
    req_file.write_text(
        """
# Dependencies
requests>=2.31.0
pytest==8.0.0
scikit-learn~=1.4.0
-r other-requirements.txt
git+https://github.com/psf/requests.git@main#egg=requests
# comment line
hallucinated-tool-xyz
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_manifest_dependencies(req_file, root, local_modules)
    extracted_names = [d.name for d in extracted]

    assert "requests" in extracted_names
    assert "pytest" in extracted_names
    assert "scikit-learn" in extracted_names
    assert "hallucinated-tool-xyz" in extracted_names
    assert "-r other-requirements.txt" in extracted_names
    assert "git+https://github.com/psf/requests.git@main#egg=requests" in extracted_names

    unscanned = [d for d in extracted if d.unscanned_reason]
    assert len(unscanned) == 2
    assert any("-r" in d.unscanned_reason for d in unscanned)
    assert any("VCS" in d.unscanned_reason for d in unscanned)


def test_extract_manifest_pyproject_toml(tmp_path: Path):
    root = tmp_path / "mock_repo"
    root.mkdir()
    pyproj_file = root / "pyproject.toml"
    pyproj_file.write_text(
        """
[project]
name = "my-sample-app"
version = "0.1.0"
dependencies = [
    "requests>=2.28.0",
    "click>=8.0.0",
    "slop-detector-agent"
]
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_manifest_dependencies(pyproj_file, root, local_modules)
    extracted_names = [d.name for d in extracted]

    assert "requests" in extracted_names
    assert "click" in extracted_names
    assert "slop-detector-agent" in extracted_names
    assert "my-sample-app" not in extracted_names


def test_git_diff_import_scoping(tmp_path: Path):
    root = tmp_path / "mock_git_repo"
    root.mkdir()

    # Initialize real git repository
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, capture_output=True, check=True)

    app_py = root / "app.py"
    app_py.write_text(
        """import sys
import requests

def existing_fn():
    return sys.version
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app.py"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=root, capture_output=True, check=True)

    # Now modify app.py adding a new external import and a new stdlib import
    app_py.write_text(
        """import sys
import requests
import json
import httpx
from pydantic import BaseModel

def existing_fn():
    return sys.version
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(app_py, root=root, local_modules=local_modules)
    extracted_names = [d.name for d in extracted]

    # Pre-existing import 'requests' should NOT be extracted because it was not added in this diff
    assert "requests" not in extracted_names
    # Stdlib 'json' should be filtered out
    assert "json" not in extracted_names
    # Newly added external imports 'httpx' and 'pydantic' SHOULD be extracted
    assert "httpx" in extracted_names
    assert "pydantic" in extracted_names

