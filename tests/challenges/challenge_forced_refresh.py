#!/usr/bin/env python3
"""
Challenge: Forced Refresh — find the service forcing segment merges.

One service appends ?refresh=true to every write, preventing ES from
batching merges efficiently.

Usage:
    python tests/challenges/challenge_forced_refresh.py
    python tests/challenges/challenge_forced_refresh.py --seed 10000 --max-docs 50000
"""

import _challenge_forced_refresh as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
