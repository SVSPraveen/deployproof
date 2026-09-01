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


def test_nested_requirements_txt_include_resolution(tmp_path: Path):
    """Verify -r includes are resolved and parsed recursively."""
    root = tmp_path / "mock_repo"
    root.mkdir()
    req_dir = root / "requirements"
    req_dir.mkdir()

    base_file = req_dir / "base.txt"
    base_file.write_text(
        "requests>=2.31.0\n"
        "fake-hallucinated-ai-pkg==1.0.0\n",
        encoding="utf-8",
    )

    main_file = root / "requirements.txt"
    main_file.write_text(
        "-r requirements/base.txt\n"
        "fastapi>=0.100.0\n",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_manifest_dependencies(main_file, root, local_modules)
    extracted_names = [d.name for d in extracted]

    # Both base.txt packages and main_file packages should be extracted
    assert "requests" in extracted_names
    assert "fake-hallucinated-ai-pkg" in extracted_names
    assert "fastapi" in extracted_names

    # Check source file pointers
    fake_dep = next(d for d in extracted if d.name == "fake-hallucinated-ai-pkg")
    assert fake_dep.source_file == base_file
    assert fake_dep.lineno == 2


def test_circular_requirements_txt_include_resolution(tmp_path: Path):
    """Verify circular requirements includes do not crash or hang in infinite loop."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    req_a = root / "requirements_a.txt"
    req_b = root / "requirements_b.txt"

    req_a.write_text(
        "-r requirements_b.txt\n"
        "package-alpha>=1.0.0\n",
        encoding="utf-8",
    )
    req_b.write_text(
        "-r requirements_a.txt\n"
        "package-beta>=2.0.0\n",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_manifest_dependencies(req_a, root, local_modules)
    extracted_names = [d.name for d in extracted]

    assert "package-alpha" in extracted_names
    assert "package-beta" in extracted_names
    # Circular include is recorded as unscanned without crashing
    unscanned = [d for d in extracted if d.unscanned_reason]
    assert len(unscanned) == 1
    assert "Circular" in unscanned[0].unscanned_reason


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


def test_dynamic_importlib_and_dunder_import_extraction(tmp_path: Path):
    """Verify importlib.import_module and __import__ string literal calls are extracted as dynamically imported."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    app_py = root / "plugin_loader.py"
    app_py.write_text(
        """import importlib
from importlib import import_module

def load_plugins():
    mod1 = importlib.import_module("fake_dynamic_plugin_alpha")
    mod2 = import_module("fake_dynamic_plugin_beta.submod")
    mod3 = __import__("fake_dynamic_plugin_gamma")
    # Stdlib dynamic imports should be ignored
    mod_sys = importlib.import_module("sys")
    mod_os = __import__("os")
    return mod1, mod2, mod3
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(app_py, root=root, local_modules=local_modules)

    extracted_names = [d.name for d in extracted]
    assert "fake_dynamic_plugin_alpha" in extracted_names
    assert "fake_dynamic_plugin_beta" in extracted_names
    assert "fake_dynamic_plugin_gamma" in extracted_names

    # Stdlib should NOT be present
    assert "sys" not in extracted_names
    assert "os" not in extracted_names

    # Verify source_type
    for d in extracted:
        assert d.source_type == "dynamically imported"


def test_dynamic_import_non_literal_argument_unscanned(tmp_path: Path):
    """Verify dynamic imports with non-literal arguments are safely recorded as unscanned without crashing."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    app_py = root / "dynamic_runner.py"
    app_py.write_text(
        """import importlib

def run_dynamic(plugin_name):
    mod = importlib.import_module(plugin_name)
    mod2 = __import__(plugin_name + "_ext")
    return mod
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(app_py, root=root, local_modules=local_modules)

    unscanned = [d for d in extracted if d.unscanned_reason]
    assert len(unscanned) == 2
    assert all("Dynamic import with non-literal name" in d.unscanned_reason for d in unscanned)


def test_requirements_manifest_file_recognition(tmp_path: Path):
    """Verify arbitrary .txt files like LICENSE.txt are ignored, while genuine requirements files are parsed."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    # 1. Non-manifest text files that should be ignored
    license_file = root / "LICENSE.txt"
    license_file.write_text(
        "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS\n"
        "NEGLIGENCE OR OTHERWISE ARISING IN ANY WAY OUT OF THE USE\n"
        "1. Redistributions of source code must retain the above notice.\n",
        encoding="utf-8",
    )
    local_modules = get_local_module_names(root)
    assert extract_new_manifest_dependencies(license_file, root, local_modules) == []

    readme_file = root / "README.txt"
    readme_file.write_text("Hello World project notes\n", encoding="utf-8")
    assert extract_new_manifest_dependencies(readme_file, root, local_modules) == []

    # 2. Genuine requirements files that should be parsed
    req_file = root / "requirements-dev.txt"
    req_file.write_text("pytest>=8.0.0\npytest-mock>=3.12.0\n", encoding="utf-8")
    deps = extract_new_manifest_dependencies(req_file, root, local_modules)
    pkg_names = [d.name for d in deps]
    assert "pytest" in pkg_names
    assert "pytest-mock" in pkg_names


def test_stdlib_annotationlib_and_internal_typeshed(tmp_path: Path):
    """Verify newer Python stdlib modules like annotationlib and _typeshed are not flagged as external dependencies."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    app_py = root / "compat.py"
    app_py.write_text(
        """
import annotationlib
from _typeshed import FileDescriptor
import tomllib
import zoneinfo
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(app_py, root=root, local_modules=local_modules)
    assert len(extracted) == 0


def test_openssl_import_mapping(tmp_path: Path):
    """Verify import OpenSSL is correctly mapped to pyOpenSSL distribution."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    app_py = root / "tls.py"
    app_py.write_text("import OpenSSL\nimport yaml\nimport bs4\nimport dateutil\n", encoding="utf-8")

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(app_py, root=root, local_modules=local_modules)
    names = {d.import_name: d.name for d in extracted}

    assert names["OpenSSL"] == "pyOpenSSL"
    assert names["yaml"] == "PyYAML"
    assert names["bs4"] == "beautifulsoup4"
    assert names["dateutil"] == "python-dateutil"

def test_legacy_python2_stdlib_compat_shims(tmp_path: Path):
    """Verify legacy Python 2 stdlib modules used in compatibility shims are recognized as stdlib and not flagged as external dependencies."""
    root = tmp_path / "mock_repo"
    root.mkdir()

    compat_py = root / "compat.py"
    compat_py.write_text(
        """
try:
    import StringIO
except ImportError:
    import io as StringIO

try:
    from cStringIO import StringIO as cStringIO
except ImportError:
    cStringIO = None

try:
    from BaseHTTPServer import HTTPServer
    from SimpleHTTPServer import SimpleHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer, SimpleHTTPRequestHandler

import urllib2
import urlparse
import httplib
import Cookie
import cookielib
import Queue
import SocketServer
import ConfigParser
import xmlrpclib
import commands
""",
        encoding="utf-8",
    )

    local_modules = get_local_module_names(root)
    extracted = extract_new_imports_from_py_file(compat_py, root=root, local_modules=local_modules)
    assert len(extracted) == 0
