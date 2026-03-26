#!/usr/bin/env python3
"""Challenge v3: The Silent Killer — find the task with no fingerprint.

One application (platform-core) runs 8 background tasks. The cluster CPU
is pinned. Cost indicator panels scream scripts, wildcards, deep aggs —
but the real culprit triggers none of them. It hides behind ordinary-looking
queries that happen to be genuinely expensive.

Usage:
    python tests/challenges/challenge_stealth.py
    python tests/challenges/challenge_stealth.py --seed 10000 --max-docs 50000
"""

import _challenge_stealth as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
