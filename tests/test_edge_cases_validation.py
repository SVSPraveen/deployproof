"""Validation test fixtures for Tier 1 AST mutator against complex Python constructs."""

import pathlib
import tempfile
from deployproof.mutator import (
    collect_skipped_constructs_for_file,
    generate_mutants_for_file,
)


FIXTURES = {
    "Decorators": '''
import functools

def custom_dec(threshold=10, is_enabled=True):
    def wrapper(fn):
        return fn
    return wrapper

@functools.lru_cache(maxsize=128)
@custom_dec(threshold=50, is_enabled=False)
def calculate(x: int) -> int:
    return x * 2
''',

    "F-strings": '''
def format_status(name: str, score: int, is_active: bool) -> str:
    msg = f"User: {name}, Status: {'Admin' if is_active else 'Guest'}, HighScore: {score > 100}, Next: {score + 1}"
    return msg
''',

    "Walrus Operator": '''
def process_data(items: list) -> int:
    if (n := len(items)) > 10:
        return n * 2
    return 0
''',

    "Async/Await": '''
async def fetch_item(item_id: int, retry: bool = True):
    if item_id <= 0:
        return None
    res = await client.get(item_id)
    if retry and res is None:
        return await client.get(item_id)
    return res
''',

    "Comprehensions": '''
def process_lists(items: list[int], d: dict) -> list[int]:
    doubled = [x * 2 for x in items if x > 0 and x % 2 == 0]
    filtered_dict = {k: v for k, v in d.items() if v != None and len(k) > 2}
    gen = (n for n in items if n < 50)
    return doubled
''',

    "Match Statements": '''
def handle_command(command: dict) -> str:
    match command:
        case {"action": "delete", "id": uid} if uid > 0:
            return "deleted"
        case [x, y] if x == y:
            return "equal_pair"
        case _:
            return "default"
''',

    "Generators (Yield)": '''
def count_even(limit: int):
    count = 0
    while count < limit:
        if count % 2 == 0:
            yield count * 10
        count += 1
'''
}


def test_edge_case_fixtures_and_skipped_constructs():
    """Run all edge-case fixtures and verify both mutants and narrowed skipped constructs."""
    results = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, code in FIXTURES.items():
            p = pathlib.Path(tmpdir) / f"{name.lower().replace(' ', '_').replace('/', '_')}.py"
            p.write_text(code, encoding="utf-8")
            try:
                mutants = generate_mutants_for_file(p)
                skipped = collect_skipped_constructs_for_file(p)
                results[name] = {
                    "status": "OK",
                    "mutants_count": len(mutants),
                    "skipped_count": len(skipped),
                    "skipped": [
                        (s.line_number, s.construct_name, s.snippet, s.description)
                        for s in skipped
                    ],
                }
            except Exception as e:
                results[name] = {
                    "status": "CRASHED",
                    "error": f"{type(e).__name__}: {e}",
                    "mutants_count": 0,
                    "skipped_count": 0,
                    "skipped": [],
                }

    assert len(results) == 7
    # Semantic risk constructs are recorded as skipped
    assert results["Walrus Operator"]["skipped_count"] >= 1
    assert results["Match Statements"]["skipped_count"] >= 1
    assert results["Generators (Yield)"]["skipped_count"] >= 1

    # Routine & upgraded constructs (decorators, comprehensions, async/await) are NOT skipped; they are mutated directly
    assert results["Async/Await"]["mutants_count"] >= 1
    assert results["Async/Await"]["skipped_count"] == 0
    assert results["Comprehensions"]["mutants_count"] >= 10
    assert results["Comprehensions"]["skipped_count"] == 0
    assert results["Decorators"]["skipped_count"] == 0


def test_type_annotations_are_excluded_from_mutation():
    """Verify PEP 604 union type annotations are never mutated."""
    code = '''
from typing import Mapping, Iterable

class DictHandler:
    def __init__(self, data: Mapping[str, int] | Iterable[tuple[str, int]] | None = None) -> None:
        self.count: int | None = None

    def get(self, key: str) -> str | bytes | None:
        return None
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        p = pathlib.Path(tmpdir) / "typed_module.py"
        p.write_text(code, encoding="utf-8")
        mutants = generate_mutants_for_file(p)
        # Should generate 0 mutants because all '|' and constants are in annotations!
        assert len(mutants) == 0, f"Expected 0 mutants in pure type annotations, got {len(mutants)}"
