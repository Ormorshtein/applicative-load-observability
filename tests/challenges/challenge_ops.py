#!/usr/bin/env python3
"""Challenge v2: Operation Forensics — find the bad task.

One application (backend-v2) runs 8 background tasks. Something is killing
your cluster. The "Stress by Application" panel is useless — all traffic
comes from a single app. Use operation types, templates, cost indicators,
and clause counts to find which task is the culprit.

Usage:
    python tests/challenges/challenge_ops.py
    python tests/challenges/challenge_ops.py --seed 10000 --max-docs 50000
"""

import _challenge_ops as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
