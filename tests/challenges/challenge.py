#!/usr/bin/env python3
"""Challenge v1: detect the stress source among 4 simulated applications.

Four apps hit a shared index simultaneously — most doing normal work, one
hiding expensive query patterns in its traffic. Monitor Kibana dashboards
to identify and kill the culprit.

Usage:
    python tests/challenges/challenge.py
    python tests/challenges/challenge.py --gateway http://host:9200
    python tests/challenges/challenge.py --seed 20000 --max-docs 100000
"""

import _challenge_v1 as _config
from _challenge_runner import main_cli

if __name__ == "__main__":
    main_cli(_config)
