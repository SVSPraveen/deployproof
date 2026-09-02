"""
Interactive Quick-Fix Mode for DeployProof.

Prompts the developer directly in the terminal to inspect and apply auto-synthesized
pytest test cases to kill surviving mutants without manual copy-pasting.
"""
import ast
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

from deployproof.mutator import Mutant
from deployproof.synthesizer import SynthesizedTest, synthesize_tests_for_surviving_mutants


def prompt_apply_synthesized_tests(
    surviving_mutants: List[Mutant],
    repo_root: Path,
    output_file_override: Optional[Path] = None,
) -> int:
    """
    Prompt the developer in the terminal to apply synthesized test cases.

    Returns the number of test cases applied.
    """
    if not surviving_mutants:
        return 0

    if not sys.stdin.isatty():
        print("\nNotice: Non-interactive shell detected. Skipping interactive quick-fix prompts.")
        return 0

    synth_tests = synthesize_tests_for_surviving_mutants(surviving_mutants, repo_root=repo_root)
    if not synth_tests:
        print("\nNotice: No targeted test synthesis strategies available for surviving mutants.")
        return 0

    print("\n" + "=" * 68)
    print(f"🔧 DeployProof Interactive Quick-Fix Mode ({len(synth_tests)} fixable mutant(s) found)")
    print("=" * 68)

    applied_count = 0
    apply_all = False
    default_test_file = output_file_override or (repo_root / "tests" / "test_deployproof_healed.py")

    for idx, st in enumerate(synth_tests, 1):
        try:
            rel_source = st.file_path.relative_to(repo_root).as_posix()
        except ValueError:
            rel_source = st.file_path.as_posix()

        print(f"\n[?] Fix {idx}/{len(synth_tests)}: {rel_source}:{st.line_number}")
        print(f"    Mutation : {st.target_mutation}")
        print(f"    Strategy : {st.strategy}")
        print("    " + "-" * 60)
        for line in st.test_code.strip().splitlines():
            print(f"    | {line}")
        print("    " + "-" * 60)

        if not apply_all:
            prompt_str = f"    Apply to '{default_test_file.name}'? [Y/n/q/all] (default: Y): "
            try:
                choice = input(prompt_str).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nInteractive quick-fix aborted by user.")
                break

            if choice in ("q", "quit", "exit"):
                print("Exiting interactive quick-fix mode.")
                break
            elif choice in ("a", "all"):
                apply_all = True
            elif choice in ("n", "no", "skip"):
                print("    [-] Skipped.")
                continue

        # Append test to file
        default_test_file.parent.mkdir(parents=True, exist_ok=True)
        if not default_test_file.exists():
            header = (
                '"""\n'
                'Auto-generated unit tests synthesized by DeployProof to kill surviving mutants.\n'
                'Run pytest on this file to verify that all surviving mutants are killed.\n'
                '"""\n'
                'import os\n'
                'import sys\n'
                'from pathlib import Path\n'
                'import pytest\n\n'
                '# Ensure src/ and repo root are in python search path\n'
                '_root = Path(__file__).resolve().parent.parent\n'
                'for _p in [str(_root / "src"), str(_root)]:\n'
                '    if _p not in sys.path:\n'
                '        sys.path.insert(0, _p)\n\n'
            )
            default_test_file.write_text(header, encoding="utf-8")

        existing_content = default_test_file.read_text(encoding="utf-8")
        if st.test_name not in existing_content:
            with open(default_test_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n{st.test_code}\n")
            print(f"    [+] Appended '{st.test_name}' to {default_test_file.name}!")
            applied_count += 1
        else:
            print(f"    [.] Test '{st.test_name}' already present in {default_test_file.name}.")

    if applied_count > 0:
        try:
            rel_out = default_test_file.relative_to(repo_root).as_posix()
        except ValueError:
            rel_out = default_test_file.as_posix()
        print("\n" + "=" * 68)
        print(f"🎉 Applied {applied_count} self-healing test(s) to {rel_out}!")
        print(f"   Run 'pytest {rel_out}' to execute and verify mutant elimination.\n")

    return applied_count
