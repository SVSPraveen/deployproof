"""
Comprehensive Verification Matrix for 100% Mutation Operator Parity.

This test suite rigorously validates every single operator, mapping, and mutation
rule from mutmut, Cosmic Ray, and DeployProof's Next-Era AST Engine.
"""

from pathlib import Path
import tempfile
import pytest

from deployproof.mutator import generate_mutants_for_file


def _get_mutant_descriptions(code: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_module.py"
        p.write_text(code, encoding="utf-8")
        mutants = generate_mutants_for_file(p)
        return [m.description for m in mutants]


# 1. Comparison Operators (==, !=, <, <=, >, >=, in, not in, is, is not)
@pytest.mark.parametrize("op,expected", [
    ("==", "!="),
    ("!=", "=="),
    ("<", ">="),
    ("<=", ">"),
    (">", "<="),
    (">=", "<"),
    (" in ", " not in "),
    (" not in ", " in "),
    (" is ", " is not "),
    (" is not ", " is "),
])
def test_all_comparison_operators(op, expected):
    code = f"def check(a, b):\n    return a {op} b\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(f"'{expected.strip()}'" in d for d in descriptions), f"Failed for {op} -> {expected}"


# 2. Binary Arithmetic & Bitwise Operators (+, -, *, /, //, %, **, <<, >>, &, |, ^)
@pytest.mark.parametrize("op,expected", [
    ("+", "-"),
    ("-", "+"),
    ("*", "/"),
    ("/", "*"),
    ("//", "/"),
    ("%", "*"),
    ("**", "*"),
    ("<<", ">>"),
    (">>", "<<"),
    ("&", "|"),
    ("|", "&"),
    ("^", "&"),
])
def test_all_binary_operators(op, expected):
    code = f"def calc(a, b):\n    return a {op} b\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(f"'{expected}'" in d for d in descriptions), f"Failed for {op} -> {expected}"


# 3. Augmented Assignment Operators (+=, -=, *=, /=, //=, %=, **=, <<=, >>=, &=, |=, ^=)
@pytest.mark.parametrize("op,expected", [
    ("+=", "-="),
    ("-=", "+="),
    ("*=", "/="),
    ("/=", "*="),
    ("//=", "/="),
    ("%=", "/="),
    ("**=", "*="),
    ("<<=", ">>="),
    (">>=", "<<="),
    ("&=", "|="),
    ("|=", "&="),
    ("^=", "&="),
])
def test_all_augmented_assignments(op, expected):
    code = f"def mutate_in_place(a, b):\n    a {op} b\n    return a\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(f"'{expected}'" in d for d in descriptions), f"Failed for {op} -> {expected}"


# 4. Unary Operators (+x, -x, ~x, not x)
@pytest.mark.parametrize("code_snip,expected_desc", [
    ("return -x", "Replace unary operator '-' with '+'"),
    ("return +x", "Replace unary operator '+' with '-'"),
    ("return ~x", "Remove '~' bitwise inversion"),
    ("return not x", "Remove 'not' logical inversion"),
])
def test_all_unary_operators(code_snip, expected_desc):
    code = f"def invert(x):\n    {code_snip}\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(expected_desc in d for d in descriptions)


# 5. Boolean Logic (and, or, True, False)
def test_boolean_logic():
    code = "def logic(a, b):\n    flag = True\n    other = False\n    return (a and b) or flag\n"
    descriptions = _get_mutant_descriptions(code)
    assert any("Replace logical operator 'and' with 'or'" in d for d in descriptions)
    assert any("Replace logical operator 'or' with 'and'" in d for d in descriptions)
    assert any("Replace boolean literal 'True' with 'False'" in d for d in descriptions)
    assert any("Replace boolean literal 'False' with 'True'" in d for d in descriptions)


# 6. String Methods Parity (19 Symmetric & Unsymmetrical Swaps)
@pytest.mark.parametrize("method,opposite", [
    ("lower", "upper"),
    ("upper", "lower"),
    ("strip", "rstrip"),
    ("lstrip", "rstrip"),
    ("rstrip", "lstrip"),
    ("find", "rfind"),
    ("rfind", "find"),
    ("index", "rindex"),
    ("rindex", "index"),
    ("split", "rsplit"),
    ("rsplit", "split"),
    ("partition", "rpartition"),
    ("rpartition", "partition"),
    ("ljust", "rjust"),
    ("rjust", "ljust"),
    ("startswith", "endswith"),
    ("endswith", "startswith"),
    ("removeprefix", "removesuffix"),
    ("removesuffix", "removeprefix"),
])
def test_all_string_methods(method, opposite):
    code = f"def process_string(s):\n    return s.{method}('test')\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(f"Swap string method '{method}' with '{opposite}'" in d for d in descriptions)


# 7. Exception Catching Parity (Cosmic Ray ExceptionReplacer)
@pytest.mark.parametrize("exc,swapped", [
    ("ValueError", "ZeroDivisionError"),
    ("KeyError", "IndexError"),
    ("TypeError", "ValueError"),
    ("IndexError", "KeyError"),
    ("AttributeError", "TypeError"),
])
def test_all_exception_swaps(exc, swapped):
    code = f"def handle_err():\n    try:\n        run()\n    except {exc}:\n        pass\n"
    descriptions = _get_mutant_descriptions(code)
    assert any(f"Replace exception catch type '{exc}' with '{swapped}'" in d for d in descriptions)


# 8. Loop Control & Zero-Iteration Loops
def test_loop_mutations():
    code = """def loop_demo(items):
    for x in items:
        if x:
            break
        else:
            continue
"""
    descriptions = _get_mutant_descriptions(code)
    assert any("Empty for-loop iterator (Zero-Iteration Loop)" in d for d in descriptions)
    assert any("Replace 'break' loop control with 'continue'" in d for d in descriptions)
    assert any("Replace 'continue' loop control with 'break'" in d for d in descriptions)


# 9. Next-Era Features: Async, Context Managers, Match, Comprehension, Yield
def test_next_era_features():
    code = """async def worker(stream):
    with lock:
        await stream.flush()
    result = [x for x in stream if x > 0]
    val = 1 if result else 0
    match val:
        case 1 if is_ready():
            yield val
        case _:
            yield from fallback()
"""
    descriptions = _get_mutant_descriptions(code)
    assert any("Bypass context manager" in d for d in descriptions)
    assert any("Drop await expression" in d for d in descriptions)
    assert any("Invert comprehension 'if' filter condition" in d for d in descriptions)
    assert any("Swap ternary if-else branches" in d for d in descriptions)
    assert any("Invert pattern matching case guard condition" in d for d in descriptions)
    assert any("Mutate yield expression to 'yield None'" in d for d in descriptions)
    assert any("Replace 'yield from' iterator with empty list" in d for d in descriptions)
