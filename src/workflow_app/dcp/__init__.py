"""DCP integration package for workflow-app (T-050).

Exposes a single module-level boolean `READER_AVAILABLE` that tells the
widgets whether the T-035 `DeliveryReader` is importable. The buttons in
`command_queue/command_queue_widget.py` rely on this flag to decide whether
`[DCP: Specific-Flow]` is enabled at init time.

The import is done as a side-effect of loading this module so the detection
runs exactly once per process. Client code MUST reference
`workflow_app.dcp.READER_AVAILABLE` (module attribute), never
`from workflow_app.dcp import READER_AVAILABLE` — otherwise monkeypatching in
tests would not affect the already-bound name in the consumer module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from workflow_app.services.delivery_reader import DeliveryReader  # noqa: F401

    READER_AVAILABLE: bool = True
except ImportError:
    READER_AVAILABLE = False
    logger.warning(
        "workflow_app.services.delivery_reader unavailable — "
        "DCP: Specific-Flow button will be disabled"
    )

__all__ = ["READER_AVAILABLE"]
