"""metrics_streamer.py — DISABLED.

The legacy fake-metrics SocketIO streamer has been retired.
Real dashboard updates are emitted by control_plane.run_control_plane_loop()
via the 'dashboard_update' event on the /metrics namespace.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MetricsStreamer:
    """No-op stub — real metrics are streamed by control_plane."""

    def start(self):
        logger.info('[metrics_streamer] Legacy streamer disabled; real DES metrics via control_plane.')

    def stop(self):
        pass


metrics_streamer = MetricsStreamer()
