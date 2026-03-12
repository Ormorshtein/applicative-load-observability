#!/usr/bin/env python3
"""
Challenge: Broad Text Match — find the search-bar spam.

One service sends 2-3 character search terms returning massive hit
counts.  No minimum query-length validation, no cost indicators.

Usage:
    python tests/challenges/challenge_broad_match.py
    python tests/challenges/challenge_broad_match.py --seed 10000 --max-docs 50000
"""

import _challenge_broad_match as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
