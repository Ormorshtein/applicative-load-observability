#!/usr/bin/env python3
"""
Challenge: Geo Broad Sweep — find the service with the giant radius.

One service uses geo_distance with 200-500km radius returning huge
result sets.  has_geo fires for many services — the radius matters.

Usage:
    python tests/challenges/challenge_geo_sweep.py
    python tests/challenges/challenge_geo_sweep.py --seed 10000 --max-docs 50000
"""

import _challenge_geo_sweep as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
