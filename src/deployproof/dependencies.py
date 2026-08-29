"""Dependency and import extraction for slopsquatting / hallucination scanning."""

import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

# Standard library module names (Python 3.10 through 3.14+)
STDLIB_MODULES: Set[str] = set(getattr(sys, "stdlib_module_names", set())) | {
    "__future__",
    "_thread",
    "_typeshed",
    "abc",
    "aifc",
    "annotationlib",
    "argparse",
    "array",
    "ast",
    "asynchat",
    "asyncio",
    "asyncore",
    "atexit",
    "audioop",
    "base64",
    "bdb",
    "binascii",
    "binhex",
    "bisect",
    "builtins",
    "bz2",
    "calendar",
    "cgi",
    "cgitb",
    "chunk",
    "cmath",
    "cmd",
    "code",
    "codecs",
    "codeop",
    "collections",
    "colorsys",
    "compileall",
    "concurrent",
    "configparser",
    "contextlib",
    "contextvars",
    "copy",
    "copyreg",
    "cProfile",
    "crypt",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "distutils",
    "doctest",
    "email",
    "encodings",
    "enum",
    "errno",
    "faulthandler",
    "fcntl",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "genericpath",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "graphlib",
    "grp",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "idlelib",
    "imaplib",
    "imghdr",
    "imp",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "lib2to3",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "mailcap",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "msilib",
    "msvcrt",
    "multiprocessing",
    "netrc",
    "nntplib",
    "ntpath",
    "numbers",
    "operator",
    "optparse",
    "os",
    "ossaudiodev",
    "parser",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posix",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "pwd",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "site",
    "smtpd",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "spwd",
    "sqlite3",
    "sre_compile",
    "sre_constants",
    "sre_parse",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symbol",
    "symtable",
    "sys",
    "sysconfig",
    "syslog",
    "tabnanny",
    "tarfile",
    "telnetlib",
    "tempfile",
    "termios",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "tkinter",
    "token",
    "tokenize",
    "tomllib",
    "trace",
    "traceback",
    "tracemalloc",
    "tty",
    "turtle",
    "turtledemo",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "winsound",
    "wsgiref",
    "xdrlib",
    "xml",
    "xmlrpc",
    "zipapp",
    "zipfile",
    "zipimport",
    "zlib",
    "zoneinfo",
}

# Mapping of common top-level Python import names to their PyPI distribution package names
IMPORT_TO_PYPI_MAP: Dict[str, str] = {
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "attr": "attrs",
    "jwt": "PyJWT",
    "serial": "pyserial",
    "usb": "pyusb",
    "websocket": "websocket-client",
    "magic": "python-magic",
    "dateutil": "python-dateutil",
    "fitz": "PyMuPDF",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodome",
    "jose": "python-jose",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "git": "GitPython",
    "Bio": "biopython",
    "psycopg2": "psycopg2",
    "google": "protobuf",
    "OpenSSL": "pyOpenSSL",
    "openssl": "pyOpenSSL",
    "OpenGL": "PyOpenGL",
    "wx": "wxPython",
    "gi": "PyGObject",
    "googleapiclient": "google-api-python-client",
    "kafka": "kafka-python",
    "pydantic_core": "pydantic-core",
    "pkg_resources": "setuptools",
    "setuptools": "setuptools",
    "brotli": "Brotli",
    "zstandard": "zstandard",
    "markupsafe": "MarkupSafe",
    "sqlalchemy": "SQLAlchemy",
    "playwright": "playwright",
}

# Known namespace umbrella roots (subpackages published separately on PyPI)
KNOWN_NAMESPACE_ROOTS: Set[str] = {
    "backports",
    "google",
    "azure",
    "oslo",
    "zope",
    "jaraco",
    "sphinxcontrib",
    "ruamel",
    "zc",
    "plone",
}

MANIFEST_FILENAMES = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
}


def is_stdlib_or_internal(module_name: str) -> bool:
    """Check if a module name is standard library, typeshed, or internal."""
    cleaned = module_name.strip()
    if not cleaned:
        return True
    if cleaned.startswith("_"):
        return True
    if cleaned in STDLIB_MODULES:
        return True
    if hasattr(sys, "stdlib_module_names") and cleaned in sys.stdlib_module_names:
        return True
    return False


def is_requirements_manifest_file(file_path: Path) -> bool:
    """
    Check if a file is a requirements manifest file based on specific naming patterns.
    
    Accepts: requirements*.txt, *-requirements.txt, requirements/*.txt, constraints.txt, *.in, etc.
    Rejects: arbitrary .txt files (LICENSE.txt, README.txt, NOTICE.txt, hello.txt, etc.).
    """
    name = file_path.name.lower()
    parent_names = [p.name.lower() for p in file_path.parents]
    in_req_dir = any(p in ("requirements", "reqs", "constraints") for p in parent_names)

    if in_req_dir and file_path.suffix in (".txt", ".in"):
        return True

    if name in ("requirements.txt", "constraints.txt", "requirements.in", "constraints.in"):
        return True

    if name.startswith("requirements") and file_path.suffix in (".txt", ".in"):
        return True

    if name.startswith("constraints") and file_path.suffix in (".txt", ".in"):
        return True

    if name.endswith(("-requirements.txt", "_requirements.txt", ".requirements.txt", "-constraints.txt", "_constraints.txt", ".constraints.txt")):
        return True

    if name.endswith(("-requirements.in", "_requirements.in", ".requirements.in", "-constraints.in", "_constraints.in", ".constraints.in")):
        return True

    if name.endswith(".in") and any(k in name for k in ("req", "dev", "test", "base", "prod", "doc")):
        return True

    return False


@dataclass(frozen=True)
class ExtractedDependency:
    """Represents a newly introduced external dependency."""

    name: str  # Normalized PyPI package name
    import_name: str  # Raw import name in code / manifest
    source_file: Path  # File where dependency was found
    lineno: Optional[int] = None  # Line number in file
    source_type: str = "import"  # "import" | "requirements.txt" | "pyproject.toml" | "setup.py"
    unscanned_reason: Optional[str] = None  # Reason if source is seen but not checked against PyPI


def get_local_module_names(root: Path) -> Set[str]:
    """
    Discover all local module and package names defined within the workspace repository.
    
    Identifies root and src/ Python files, folders containing __init__.py or .py files,
    and configured project package names to prevent flagging local imports.
    """
    local_names: Set[str] = set()

    search_dirs = [root, root / "src", root / "lib", root / "app", root / "tests", root / "test", root / "examples"]
    for s_dir in search_dirs:
        if not s_dir.is_dir():
            continue
        try:
            for entry in s_dir.iterdir():
                if entry.name.startswith((".", "_")) and entry.name != "__init__.py":
                    continue
                if entry.is_file() and entry.suffix == ".py":
                    local_names.add(entry.stem)
                elif entry.is_dir():
                    # Check if directory contains python files or __init__.py
                    has_py = any(p.suffix == ".py" for p in entry.glob("*.py"))
                    if has_py or (entry / "__init__.py").exists():
                        local_names.add(entry.name)
        except (PermissionError, OSError):
            continue

    # Also scan recursively for package directories
    try:
        for py_file in root.rglob("*.py"):
            if not any(part.startswith(".") or part in ("venv", ".venv", "build", "dist", "node_modules", "__pycache__") for part in py_file.parts):
                local_names.add(py_file.stem)
                local_names.add(py_file.parent.name)
    except (PermissionError, OSError):
        pass

    return local_names


def get_added_linenos_for_file(file_path: Path, root: Path, base: Optional[str] = None) -> Optional[Set[int]]:
    """
    Get the set of 1-indexed line numbers added to a file based on git diff.
    
    Returns None if the file is untracked/new (meaning all lines are new).
    """
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        rel_path = file_path

    # Check if untracked in git status
    res_status = subprocess.run(
        ["git", "status", "--porcelain", "--", str(rel_path)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res_status.returncode == 0:
        output = res_status.stdout.strip()
        if output.startswith("??"):
            return None  # Entirely new/untracked file

    # Run git diff to find added lines
    diff_cmd = ["git", "diff", "-U0"]
    if base:
        diff_cmd.append(base)
    else:
        diff_cmd.append("HEAD")
    diff_cmd.extend(["--", str(rel_path)])

    res_diff = subprocess.run(
        diff_cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if res_diff.returncode != 0:
        return None

    diff_text = res_diff.stdout
    if not diff_text.strip():
        # Diff against HEAD is empty, check cached (staged) diff
        res_cached = subprocess.run(
            ["git", "diff", "--cached", "-U0", "--", str(rel_path)],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if res_cached.returncode == 0:
            diff_text = res_cached.stdout

    if not diff_text.strip():
        # No diff detected, treat all lines as relevant if in session
        return None

    added_lines: Set[int] = set()
    # Parse unified diff hunk headers: @@ -old,count +new,count @@
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    current_line = 0
    in_hunk = False

    for line in diff_text.splitlines():
        hunk_m = hunk_re.match(line)
        if hunk_m:
            in_hunk = True
            current_line = int(hunk_m.group(1))
            count = int(hunk_m.group(2)) if hunk_m.group(2) is not None else 1
            if count == 0:
                in_hunk = False
            continue

        if in_hunk:
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.add(current_line)
                current_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass  # Deleted line does not advance added line counter
            else:
                current_line += 1

    return added_lines


def normalize_package_name(raw_name: str) -> str:
    """Normalize import or package name to canonical PyPI package identifier."""
    cleaned = raw_name.strip()
    if cleaned in IMPORT_TO_PYPI_MAP:
        return IMPORT_TO_PYPI_MAP[cleaned]
    for imp_k, pypi_v in IMPORT_TO_PYPI_MAP.items():
        if imp_k.lower() == cleaned.lower():
            return pypi_v
    return cleaned


def extract_new_imports_from_py_file(
    file_path: Path,
    root: Path,
    local_modules: Set[str],
    base: Optional[str] = None,
) -> List[ExtractedDependency]:
    """
    Extract newly added external imports from a modified or new Python file.
    
    Filters out Python standard library modules, relative imports, and local repo packages.
    """
    if not file_path.is_file() or file_path.suffix != ".py":
        return []

    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source_code, filename=str(file_path))
    except Exception:
        return []

    added_linenos = get_added_linenos_for_file(file_path, root, base=base)
    extracted: List[ExtractedDependency] = []
    seen: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Check line number
            if added_linenos is not None and node.lineno not in added_linenos:
                continue

            for alias in node.names:
                top_name = alias.name.split(".")[0]
                if is_stdlib_or_internal(top_name) or top_name in local_modules:
                    continue
                pypi_name = normalize_package_name(top_name)
                key = f"{pypi_name}:{node.lineno}"
                if key not in seen:
                    seen.add(key)
                    extracted.append(
                        ExtractedDependency(
                            name=pypi_name,
                            import_name=alias.name,
                            source_file=file_path,
                            lineno=node.lineno,
                            source_type="import",
                        )
                    )

        elif isinstance(node, ast.ImportFrom):
            # Relative imports (node.level > 0) are always internal/local
            if node.level > 0 or not node.module:
                continue

            if added_linenos is not None and node.lineno not in added_linenos:
                continue

            top_name = node.module.split(".")[0]
            if is_stdlib_or_internal(top_name) or top_name in local_modules:
                continue

            pypi_name = normalize_package_name(top_name)
            key = f"{pypi_name}:{node.lineno}"
            if key not in seen:
                seen.add(key)
                extracted.append(
                    ExtractedDependency(
                        name=pypi_name,
                        import_name=node.module,
                        source_file=file_path,
                        lineno=node.lineno,
                        source_type="import",
                    )
                )

        elif isinstance(node, ast.Call):
            if added_linenos is not None and node.lineno not in added_linenos:
                continue

            is_importlib = False
            is_dunder_import = False

            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "import_module":
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib":
                        is_importlib = True
                    elif isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "importlib":
                        is_importlib = True
            elif isinstance(node.func, ast.Name):
                if node.func.id == "import_module":
                    is_importlib = True
                elif node.func.id == "__import__":
                    is_dunder_import = True

            if is_importlib or is_dunder_import:
                call_label = "importlib.import_module" if is_importlib else "__import__"
                if not node.args:
                    continue

                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    raw_mod_name = first_arg.value.strip()
                    top_name = raw_mod_name.split(".")[0]
                    if not top_name or is_stdlib_or_internal(top_name) or top_name in local_modules:
                        continue

                    pypi_name = normalize_package_name(top_name)
                    key = f"{pypi_name}:{node.lineno}:dynamic"
                    if key not in seen:
                        seen.add(key)
                        extracted.append(
                            ExtractedDependency(
                                name=pypi_name,
                                import_name=raw_mod_name,
                                source_file=file_path,
                                lineno=node.lineno,
                                source_type="dynamically imported",
                            )
                        )
                else:
                    # Non-literal argument, e.g. importlib.import_module(var)
                    key = f"unscanned_dynamic:{node.lineno}"
                    if key not in seen:
                        seen.add(key)
                        extracted.append(
                            ExtractedDependency(
                                name=f"{call_label}(...)",
                                import_name=f"{call_label}(...)",
                                source_file=file_path,
                                lineno=node.lineno,
                                source_type="dynamically imported",
                                unscanned_reason="Dynamic import with non-literal name - cannot verify statically",
                            )
                        )

    return extracted


MAX_INCLUDE_DEPTH = 5


def _parse_requirements_file(
    file_path: Path,
    root: Path,
    local_modules: Set[str],
    added_linenos: Optional[Set[int]] = None,
    visited_files: Optional[Set[Path]] = None,
    depth: int = 0,
) -> List[ExtractedDependency]:
    """Parse a requirements.txt file and follow -r/--requirement includes recursively."""
    if visited_files is None:
        visited_files = set()

    canonical_path = file_path.resolve()
    if canonical_path in visited_files or depth > MAX_INCLUDE_DEPTH:
        return []
    visited_files.add(canonical_path)

    if not file_path.is_file():
        return []

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    extracted: List[ExtractedDependency] = []
    lines = content.splitlines()
    req_name_re = re.compile(r"^\s*([A-Za-z0-9_\-\.]+)(?:[>=<!~;\[\s]|$)")

    for idx, line in enumerate(lines, start=1):
        raw_line = line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue

        if added_linenos is not None and idx not in added_linenos:
            continue

        # Handle -r / --requirement includes
        if raw_line.startswith(("-r ", "-r=", "--requirement ", "--requirement=")):
            if raw_line.startswith(("-r ", "-r=")):
                include_target_raw = raw_line[3:].strip().strip("\"'")
            else:
                include_target_raw = raw_line[14:].strip().strip("\"'")

            nested_file = (file_path.parent / include_target_raw).resolve()
            if nested_file.is_file() and nested_file not in visited_files and depth < MAX_INCLUDE_DEPTH:
                # Recursively parse nested requirements file (all lines in included file are evaluated)
                nested_deps = _parse_requirements_file(
                    file_path=nested_file,
                    root=root,
                    local_modules=local_modules,
                    added_linenos=None,
                    visited_files=visited_files,
                    depth=depth + 1,
                )
                extracted.extend(nested_deps)
            else:
                if not nested_file.is_file():
                    reason = f"External requirements file include not found ({include_target_raw}) - seen, not checked"
                elif nested_file in visited_files:
                    reason = f"Circular requirements file include ({include_target_raw}) - seen, not checked"
                else:
                    reason = f"External requirements file include depth limit exceeded ({include_target_raw}) - seen, not checked"
                try:
                    rel_source_type = file_path.relative_to(root).as_posix()
                except ValueError:
                    rel_source_type = file_path.name
                extracted.append(
                    ExtractedDependency(
                        name=raw_line,
                        import_name=raw_line,
                        source_file=file_path,
                        lineno=idx,
                        source_type=rel_source_type,
                        unscanned_reason=reason,
                    )
                )
            continue

        # Handle VCS lines (git+, hg+, svn+, bzr+) and direct URLs
        if any(
            raw_line.startswith(prefix)
            for prefix in (
                "git+",
                "hg+",
                "svn+",
                "bzr+",
                "-e git+",
                "-e hg+",
                "-e svn+",
                "-e bzr+",
                "http://",
                "https://",
                "-e http://",
                "-e https://",
            )
        ):
            try:
                rel_source_type = file_path.relative_to(root).as_posix()
            except ValueError:
                rel_source_type = file_path.name
            extracted.append(
                ExtractedDependency(
                    name=raw_line,
                    import_name=raw_line,
                    source_file=file_path,
                    lineno=idx,
                    source_type=rel_source_type,
                    unscanned_reason="VCS / direct URL dependency - seen, not checked",
                )
            )
            continue

        # Other pip flags like -i, -f, --extra-index-url, --find-links
        if raw_line.startswith(("-f ", "-i ", "--", "-e ")):
            continue

        m = req_name_re.match(raw_line)
        if m:
            pkg_name = m.group(1).strip()
            if not is_stdlib_or_internal(pkg_name) and pkg_name not in local_modules:
                try:
                    rel_source_type = file_path.relative_to(root).as_posix()
                except ValueError:
                    rel_source_type = file_path.name
                extracted.append(
                    ExtractedDependency(
                        name=normalize_package_name(pkg_name),
                        import_name=pkg_name,
                        source_file=file_path,
                        lineno=idx,
                        source_type=rel_source_type,
                    )
                )

    return extracted


def extract_new_manifest_dependencies(
    file_path: Path,
    root: Path,
    local_modules: Optional[Set[str]] = None,
    base: Optional[str] = None,
) -> List[ExtractedDependency]:
    """
    Extract external dependencies from modified manifest files (requirements.txt, pyproject.toml, etc.).
    """
    if local_modules is None:
        local_modules = get_local_module_names(root)

    name = file_path.name.lower()
    is_requirements = is_requirements_manifest_file(file_path)
    is_pyproject = name == "pyproject.toml"
    is_setup_py = name == "setup.py"
    is_setup_cfg = name == "setup.cfg"

    if not (is_requirements or is_pyproject or is_setup_py or is_setup_cfg):
        return []

    added_linenos = get_added_linenos_for_file(file_path, root, base=base)

    if is_requirements:
        return _parse_requirements_file(
            file_path=file_path,
            root=root,
            local_modules=local_modules,
            added_linenos=added_linenos,
        )

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    extracted: List[ExtractedDependency] = []
    lines = content.splitlines()
    dep_str_re = re.compile(r"""["']([A-Za-z0-9_\-\.]+)(?:[>=<!~;\[\s"']|$)""")

    in_dependency_section = False
    in_dependency_array = False

    for idx, line in enumerate(lines, start=1):
        raw_line = line.strip()
        lower_line = raw_line.lower()

        if is_pyproject:
            # Check section headers
            if raw_line.startswith("[") and raw_line.endswith("]"):
                header = raw_line.strip("[]").strip().lower()
                if "dependencies" in header or header.endswith(".dependencies") or "optional-dependencies" in header:
                    in_dependency_section = True
                else:
                    in_dependency_section = False
                continue

            # Check array openers like dependencies = [ or dev = [
            if "dependencies" in lower_line and "=" in raw_line and "[" in raw_line:
                in_dependency_array = True
            elif ("requires" in lower_line or "install_requires" in lower_line) and "=" in raw_line and "[" in raw_line:
                in_dependency_array = True

            if in_dependency_array and "]" in raw_line:
                # End of array on this line (we still parse this line below)
                array_ended_here = True
            else:
                array_ended_here = False

            if in_dependency_section or in_dependency_array:
                if added_linenos is None or idx in added_linenos:
                    m = dep_str_re.search(raw_line)
                    if m:
                        pkg_name = m.group(1).strip()
                        if pkg_name.lower() not in ("dependencies", "install_requires", "requires", "version", "name"):
                            if not is_stdlib_or_internal(pkg_name) and pkg_name not in local_modules:
                                extracted.append(
                                    ExtractedDependency(
                                        name=normalize_package_name(pkg_name),
                                        import_name=pkg_name,
                                        source_file=file_path,
                                        lineno=idx,
                                        source_type=file_path.name,
                                    )
                                )

            if array_ended_here:
                in_dependency_array = False

        elif is_setup_py or is_setup_cfg:
            if "install_requires" in lower_line or "extras_require" in lower_line:
                in_dependency_section = True
            if in_dependency_section and (")" in raw_line or "]" in raw_line):
                in_dependency_section = False

            if in_dependency_section:
                if added_linenos is None or idx in added_linenos:
                    m = dep_str_re.search(raw_line)
                    if m:
                        pkg_name = m.group(1).strip()
                        if pkg_name.lower() not in ("install_requires", "extras_require", "setup", "name", "version"):
                            if not is_stdlib_or_internal(pkg_name) and pkg_name not in local_modules:
                                extracted.append(
                                    ExtractedDependency(
                                        name=normalize_package_name(pkg_name),
                                        import_name=pkg_name,
                                        source_file=file_path,
                                        lineno=idx,
                                        source_type=file_path.name,
                                    )
                                )

    return extracted


def extract_all_new_dependencies(
    session_files: List[Path],
    root: Path,
    base: Optional[str] = None,
) -> List[ExtractedDependency]:
    """
    Extract all newly added external dependencies from modified Python files and manifests in session.
    """
    local_modules = get_local_module_names(root)
    all_deps: List[ExtractedDependency] = []
    seen_unique: Set[str] = set()

    for p in session_files:
        if p.suffix == ".py":
            py_deps = extract_new_imports_from_py_file(p, root, local_modules=local_modules, base=base)
            for d in py_deps:
                key = f"{d.name}:{d.source_file}:{d.lineno}"
                if key not in seen_unique:
                    seen_unique.add(key)
                    all_deps.append(d)
        else:
            manifest_deps = extract_new_manifest_dependencies(p, root, local_modules=local_modules, base=base)
            for d in manifest_deps:
                key = f"{d.name}:{d.source_file}:{d.lineno}"
                if key not in seen_unique:
                    seen_unique.add(key)
                    all_deps.append(d)

    return all_deps


@dataclass(frozen=True)
class DependencyCheckResult:
    """Detailed verification result for a single extracted dependency."""

    package_name: str
    import_name: str
    source_file: Path
    lineno: Optional[int]
    source_type: str
    status: str  # "HIGH_RISK" | "MEDIUM_RISK" | "OK" | "UNKNOWN"
    age_days: Optional[int]
    first_release_date: Optional[str]
    details: str


@dataclass(frozen=True)
class DependencyScanSummary:
    """Aggregated scan summary for all newly introduced dependencies."""

    total_scanned: int
    high_risk_count: int
    medium_risk_count: int
    ok_count: int
    unknown_count: int
    findings: List[DependencyCheckResult]
    duration_seconds: float
    unscanned_count: int = 0


def query_pypi_registry(
    package_name: str,
    cache: Optional[Dict[str, tuple]] = None,
    timeout: float = 5.0,
) -> tuple:
    """
    Query the real PyPI JSON API to verify package existence and registration age.
    
    Returns (status, age_days, first_release_date, details):
      - status: "HIGH_RISK" (404 / doesn't exist), "MEDIUM_RISK" (<30 days old), "OK" (>=30 days old), "UNKNOWN" (network error)
      - age_days: int or None
      - first_release_date: str or None
      - details: str
    """
    import datetime
    import json
    import urllib.error
    import urllib.request

    norm_name = package_name.strip()
    if is_stdlib_or_internal(norm_name):
        return ("OK", None, None, f"Standard library / internal module ({norm_name})")

    if norm_name.lower() in KNOWN_NAMESPACE_ROOTS:
        return ("OK", None, None, f"Namespace package umbrella root ('{norm_name}') - subpackages published separately on PyPI")

    if cache is not None and norm_name in cache:
        return cache[norm_name]

    # Map import name to PyPI distribution name if known
    canonical_pkg = normalize_package_name(norm_name)

    url = f"https://pypi.org/pypi/{canonical_pkg}/json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DeployProof/0.1.8 (https://github.com/SVSPraveen/DeployProof)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                releases = data.get("releases", {})
                timestamps: List[datetime.datetime] = []

                for ver, files in releases.items():
                    for f in files:
                        t_str = f.get("upload_time_iso_8601") or f.get("upload_time")
                        if t_str:
                            try:
                                dt = datetime.datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                                timestamps.append(dt)
                            except Exception:
                                pass

                if not timestamps:
                    if canonical_pkg.lower() in KNOWN_NAMESPACE_ROOTS or norm_name.lower() in KNOWN_NAMESPACE_ROOTS:
                        result = ("OK", None, None, f"Namespace package umbrella root ('{canonical_pkg}') - subpackages published separately on PyPI")
                    else:
                        result = ("MEDIUM_RISK", 0, None, "Package exists on PyPI but has 0 uploaded releases")
                else:
                    earliest_dt = min(timestamps)
                    now = datetime.datetime.now(datetime.timezone.utc)
                    age_days = max((now - earliest_dt).days, 0)
                    first_date_str = earliest_dt.strftime("%Y-%m-%d")

                    if age_days < 30:
                        result = (
                            "MEDIUM_RISK",
                            age_days,
                            first_date_str,
                            f"Recently registered package ({age_days} day{'s' if age_days != 1 else ''} old, first published {first_date_str}) - potential slopsquat / supply chain risk",
                        )
                    else:
                        result = (
                            "OK",
                            age_days,
                            first_date_str,
                            f"Established package ({age_days} days old, first published {first_date_str})",
                        )

            else:
                result = ("UNKNOWN", None, None, f"PyPI returned HTTP status {resp.status}")

    except urllib.error.HTTPError as e:
        if e.code == 404:
            if canonical_pkg.lower() in KNOWN_NAMESPACE_ROOTS or norm_name.lower() in KNOWN_NAMESPACE_ROOTS:
                result = ("OK", None, None, f"Namespace package umbrella root ('{norm_name}') - subpackages published separately on PyPI")
            else:
                result = (
                    "HIGH_RISK",
                    None,
                    None,
                    "Package does NOT exist on PyPI (HTTP 404) - hallucinated package name / slopsquatting vulnerability",
                )
        else:
            result = ("UNKNOWN", None, None, f"PyPI HTTP Error {e.code}: {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        result = ("UNKNOWN", None, None, f"Network / registry connection error: {str(e)}")
    except Exception as e:
        result = ("UNKNOWN", None, None, f"Unexpected error querying PyPI: {str(e)}")

    if cache is not None:
        cache[norm_name] = result

    return result


def scan_dependencies(
    extracted_deps: List[ExtractedDependency],
    timeout: float = 5.0,
) -> DependencyScanSummary:
    """
    Perform slopsquatting and hallucination verification against PyPI for all extracted dependencies.
    """
    import time

    start_time = time.time()
    cache: Dict[str, tuple] = {}
    findings: List[DependencyCheckResult] = []

    high_risk = 0
    medium_risk = 0
    ok_count = 0
    unknown_count = 0
    unscanned_count = 0

    for dep in extracted_deps:
        if dep.unscanned_reason:
            unscanned_count += 1
            findings.append(
                DependencyCheckResult(
                    package_name=dep.name,
                    import_name=dep.import_name,
                    source_file=dep.source_file,
                    lineno=dep.lineno,
                    source_type=dep.source_type,
                    status="UNSCANNED",
                    age_days=None,
                    first_release_date=None,
                    details=dep.unscanned_reason,
                )
            )
            continue

        status, age_days, first_date, details = query_pypi_registry(dep.name, cache=cache, timeout=timeout)

        if status == "HIGH_RISK":
            high_risk += 1
        elif status == "MEDIUM_RISK":
            medium_risk += 1
        elif status == "OK":
            ok_count += 1
        else:
            unknown_count += 1

        findings.append(
            DependencyCheckResult(
                package_name=dep.name,
                import_name=dep.import_name,
                source_file=dep.source_file,
                lineno=dep.lineno,
                source_type=dep.source_type,
                status=status,
                age_days=age_days,
                first_release_date=first_date,
                details=details,
            )
        )

    duration = round(time.time() - start_time, 2)

    return DependencyScanSummary(
        total_scanned=len(extracted_deps),
        high_risk_count=high_risk,
        medium_risk_count=medium_risk,
        ok_count=ok_count,
        unknown_count=unknown_count,
        findings=findings,
        duration_seconds=duration,
        unscanned_count=unscanned_count,
    )

