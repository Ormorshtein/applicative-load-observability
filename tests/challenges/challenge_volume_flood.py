#!/usr/bin/env python3
"""
Challenge: Volume Flood — find the service drowning the cluster.

One service polls for recent items at extreme rate.  Each query is
cheap, but the volume dwarfs all other services combined.

Usage:
    python tests/challenges/challenge_volume_flood.py
    python tests/challenges/challenge_volume_flood.py --seed 10000 --max-docs 50000
"""

import _challenge_volume_flood as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
