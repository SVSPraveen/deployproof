#!/usr/bin/env bash
# DeployProof Launch-Day Stress Test Runner
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
python "${DIR}/run_stress_tests.py"
