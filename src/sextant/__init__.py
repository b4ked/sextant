"""Sextant: local-first, CPU-only, air-gapped document search."""

from sextant._offline import enforce_offline

# Must run before anything imports huggingface_hub / transformers: those libraries
# read their offline switches once, at import time.
enforce_offline()

__version__ = "0.1.0"
