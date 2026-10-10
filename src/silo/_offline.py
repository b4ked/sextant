"""The air-gap switch.

SILO never needs the network to index or search. The only code path that
downloads anything is ``silo models pull``, which runs in a child process
with ``SILO_ALLOW_NETWORK=1``. Every other process forces the model
libraries into offline mode, so a missing model is a clear local error rather
than a silent download attempt.
"""

from __future__ import annotations

import logging
import os
import warnings

ALLOW_ENV = "SILO_ALLOW_NETWORK"


def network_allowed() -> bool:
    return os.environ.get(ALLOW_ENV) == "1"


def enforce_offline() -> None:
    # Telemetry is off in every mode.
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    if network_allowed():
        return
    # Nothing downloads outside `models pull`, so the libraries' progress bars and
    # informational chatter are noise in normal operation. Filters (unlike levels)
    # survive the libraries reconfiguring their own loggers.
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    for name in ("RapidOCR", "docling", "docling_core"):
        logging.getLogger(name).addFilter(lambda record: record.levelno >= logging.WARNING)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
