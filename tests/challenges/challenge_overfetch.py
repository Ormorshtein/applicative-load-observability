#!/usr/bin/env python3
"""
Challenge: Over-Fetching — find the service skipping pagination.

One service requests 2000-5000 documents per query.  No pagination,
no cost indicators — stress comes from the size component alone.

Usage:
    python tests/challenges/challenge_overfetch.py
    python tests/challenges/challenge_overfetch.py --seed 10000 --max-docs 50000
"""

import _challenge_overfetch as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
