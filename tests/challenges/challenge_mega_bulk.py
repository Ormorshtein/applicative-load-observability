#!/usr/bin/env python3
"""
Challenge: Oversized Bulk — find the service sending mega-batches.

One service sends infrequent but massive bulk requests (5000-10000 docs).
Each request takes seconds and blocks cluster resources.

Usage:
    python tests/challenges/challenge_mega_bulk.py
    python tests/challenges/challenge_mega_bulk.py --seed 10000 --max-docs 50000
"""

import _challenge_mega_bulk as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
