#!/usr/bin/env python3
"""
Challenge: Geo Sort + Large Fetch — find the distance-sorting hog.

One service combines geo_distance sort with size 1000-3000.  has_geo
fires for innocent tasks too — watch for expensive sorts.

Usage:
    python tests/challenges/challenge_geo_sort.py
    python tests/challenges/challenge_geo_sort.py --seed 10000 --max-docs 50000
"""

import _challenge_geo_sort as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
