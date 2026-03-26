#!/usr/bin/env python3
"""
Challenge: Unfiltered Aggregations — find the analytics hog.

One service runs match_all with 6-8 aggregations (below the deep_aggs
threshold of 10) and size 100-500.  No cost indicators trigger.

Usage:
    python tests/challenges/challenge_unfiltered_aggs.py
    python tests/challenges/challenge_unfiltered_aggs.py --seed 10000 --max-docs 50000
"""

import _challenge_unfiltered_aggs as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
