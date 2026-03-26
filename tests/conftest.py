import os
import sys

_root = os.path.join(os.path.dirname(__file__), "..")

# Add project root so tests can import the analyzer and shared packages
sys.path.insert(0, _root)
