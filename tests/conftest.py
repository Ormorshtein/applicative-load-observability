import sys
import os

# Add analyzer directory to path so tests can import parser, stress, record_builder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "analyzer"))
