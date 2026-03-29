#!/usr/bin/env python3
"""
Challenge: Large Terms Lookup — find the IN-clause abuser.

One service sends terms queries with 200-400 values — below the 500
threshold for large_terms_list.  No cost indicators trigger.

Usage:
    python tests/challenges/challenge_terms_lookup.py
    python tests/challenges/challenge_terms_lookup.py --seed 10000 --max-docs 50000
"""

import _challenge_terms_lookup as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
