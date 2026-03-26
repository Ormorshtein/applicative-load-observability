import sys
import os

_root = os.path.join(os.path.dirname(__file__), "..")

# Add project root so tests can import the shared package
sys.path.insert(0, _root)
# Add analyzer directory so tests can import parser, stress, record_builder
sys.path.insert(0, os.path.join(_root, "analyzer"))
