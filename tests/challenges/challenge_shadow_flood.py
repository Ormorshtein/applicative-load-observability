#!/usr/bin/env python3
"""
Challenge: Shadow Flood — find the invisible flood.

One service sends the exact same query templates as noise but at 10x
the rate.  Template analysis is useless — this requires process of
elimination.

Usage:
    python tests/challenges/challenge_shadow_flood.py
    python tests/challenges/challenge_shadow_flood.py --seed 10000 --max-docs 50000
"""

import _challenge_shadow_flood as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
