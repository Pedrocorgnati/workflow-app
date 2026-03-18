"""
Remote-control constants — PC side.

These values MUST stay in sync with Android RemoteConstants.kt.
Any change here MUST be reflected in the Kotlin counterpart.
"""

from __future__ import annotations

# ── Networking ──────────────────────────────────────────────────────────────

DEFAULT_PORT: int = 18765
PORT_SCAN_RANGE: range = range(18765, 18775)  # tries up to 10 ports
PORT_RANGE_SIZE: int = len(PORT_SCAN_RANGE)   # convenience alias: number of ports tried

# Tailscale CGNAT address prefix — server only accepts clients in this range
TAILSCALE_ADDR_PREFIX: str = "100."

# ── Throttle / Buffering ─────────────────────────────────────────────────────

THROTTLE_PC_MS: int = 100         # output_chunk flush interval (ms)
THROTTLE_ANDROID_MS: int = 200    # minimum ms between rendered output frames on Android
MAX_BATCH_KB: int = 4             # flush immediately when buffer >= 4 KB
MAX_BUFFER_LINES: int = 5000      # per-flush cap; older lines are discarded
SYNC_OUTPUT_LINES: int = 500      # last N lines included in pipeline snapshot

# ── Heartbeat ───────────────────────────────────────────────────────────────

PING_INTERVAL_S: int = 30         # RFC 6455 ping every 30 s

# ── Security / Rate limiting ─────────────────────────────────────────────────

MAX_PAYLOAD_BYTES: int = 1024 * 1024   # 1 MB per message hard limit
MAX_MESSAGE_BYTES: int = 65536         # 64 KB per inbound message; > → discard before parse
RATE_LIMIT_MSG_PER_S: int = 20         # max inbound messages/s; > → close 1008

# ── Deduplication ────────────────────────────────────────────────────────────

DEDUP_SET_LIMIT: int = 10_000          # max message_ids kept in processed-ids set (FIFO eviction)

# ── Reconnect (informational — enforced on Android side) ────────────────────

BACKOFF_INITIAL_S: int = 2
BACKOFF_MAX_S: int = 60
MAX_RETRY_ATTEMPTS: int = 3
BACKGROUND_DISCONNECT_MIN: int = 5

# ── Protocol whitelists ──────────────────────────────────────────────────────

ALLOWED_INBOUND_TYPES: frozenset[str] = frozenset(
    {"control", "interaction_response", "sync_request"}
)
ALLOWED_CONTROL_ACTIONS: frozenset[str] = frozenset({"play", "pause", "skip"})
