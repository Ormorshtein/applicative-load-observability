#!/usr/bin/env python3
"""
Challenge: Low Stress, High CPU — find the blind-spot exploit.

Stress scores are low everywhere, but cluster CPU is pinned.  The stress
formula has a blind spot — correlate CPU timeline with your actions.

Usage:
    python tests/challenges/challenge_hidden_cpu.py
    python tests/challenges/challenge_hidden_cpu.py --seed 10000 --max-docs 50000
"""

import _challenge_hidden_cpu as _config
from _trivial_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
