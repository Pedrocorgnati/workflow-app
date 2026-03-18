"""Unit tests for workflow_app.remote.constants."""


from workflow_app.remote.constants import (
    BACKOFF_INITIAL_S,
    BACKOFF_MAX_S,
    DEDUP_SET_LIMIT,
    DEFAULT_PORT,
    MAX_BATCH_KB,
    MAX_BUFFER_LINES,
    MAX_PAYLOAD_BYTES,
    PORT_RANGE_SIZE,
    PORT_SCAN_RANGE,
    RATE_LIMIT_MSG_PER_S,
    SYNC_OUTPUT_LINES,
    THROTTLE_ANDROID_MS,
    THROTTLE_PC_MS,
)


def test_throttle_values():
    assert THROTTLE_PC_MS == 100
    assert THROTTLE_ANDROID_MS == 200
    assert THROTTLE_ANDROID_MS > THROTTLE_PC_MS


def test_buffer_limits():
    assert MAX_BATCH_KB == 4
    assert MAX_BUFFER_LINES == 5000


def test_sync_output_lines_within_buffer():
    """Lines sent in sync must fit in the Android buffer."""
    assert SYNC_OUTPUT_LINES <= MAX_BUFFER_LINES


def test_backoff_range():
    assert BACKOFF_INITIAL_S == 2
    assert BACKOFF_MAX_S == 60
    assert BACKOFF_MAX_S > BACKOFF_INITIAL_S


def test_network_constants():
    assert DEFAULT_PORT == 18765
    assert 1024 <= DEFAULT_PORT <= 65535  # unprivileged port


def test_port_scan_range():
    assert DEFAULT_PORT in PORT_SCAN_RANGE
    assert len(PORT_SCAN_RANGE) == PORT_RANGE_SIZE
    assert PORT_RANGE_SIZE == 10


def test_port_range_does_not_overflow():
    assert max(PORT_SCAN_RANGE) <= 65535


def test_dedup_set_limit():
    assert DEDUP_SET_LIMIT == 10_000


def test_rate_limit():
    assert RATE_LIMIT_MSG_PER_S == 20


def test_max_payload_bytes():
    assert MAX_PAYLOAD_BYTES == 1024 * 1024


def test_barrel_import_constants():
    from workflow_app.remote import (
        DEDUP_SET_LIMIT as DL,
    )
    from workflow_app.remote import (
        PORT_RANGE_SIZE as PRS,
    )
    from workflow_app.remote import (
        THROTTLE_ANDROID_MS as TAM,
    )
    from workflow_app.remote import (
        THROTTLE_PC_MS as TPC,
    )

    assert TPC == 100
    assert TAM == 200
    assert PRS == 10
    assert DL == 10_000
