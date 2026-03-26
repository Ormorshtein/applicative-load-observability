#!/usr/bin/env python3
"""
Challenge: Micro-Bulk Flood — find the service wasting bulk overhead.

One service wraps every individual write in a _bulk call with 1-3
documents and fires at extreme rate.

Usage:
    python tests/challenges/challenge_micro_bulk.py
    python tests/challenges/challenge_micro_bulk.py --seed 10000 --max-docs 50000
"""

import _challenge_micro_bulk as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
