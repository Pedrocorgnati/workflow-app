package com.workflowapp.remote.connection

/**
 * Mirror of Python constants.py — all networking values must stay in sync.
 * Any changes here MUST be reflected in src/remote/constants.py on the PC side.
 */
object RemoteConstants {
    const val DEFAULT_PORT: Int          = 18765
    const val THROTTLE_PC_MS: Int        = 100
    const val THROTTLE_ANDROID_MS: Int   = 200
    const val MAX_BATCH_KB: Int          = 4
    /** Max lines kept in the local UI output buffer (ViewModel memory limit).
     *  Intentionally larger than [SYNC_OUTPUT_LINES] — the UI buffers more than
     *  what is requested in a single sync_request so scrolling back is smooth. */
    const val MAX_BUFFER_LINES: Int      = 5000
    const val INITIAL_BACKOFF_S: Long    = 2L
    const val MAX_BACKOFF_S: Long        = 60L
    const val MAX_RETRY_ATTEMPTS: Int    = 3
    const val BACKGROUND_DISCONNECT_MIN: Int = 5
    const val PING_INTERVAL_MS: Long     = 30_000L
    const val PING_TIMEOUT_MS: Long      = 10_000L
    const val CONNECT_TIMEOUT_S: Long    = 10L
    /** Debounce applied to control commands (play/pause/skip) to prevent double-tap spam. */
    const val CONTROL_DEBOUNCE_MS: Long  = 1_000L
    /** Maximum random jitter added to each backoff interval to prevent thundering herd. */
    const val MAX_JITTER_MS: Long        = 500L
    /** Lines requested from the server in sync_request on connect/reconnect.
     *  Controls the network payload; [MAX_BUFFER_LINES] controls the UI buffer. */
    const val SYNC_OUTPUT_LINES: Int     = 500
    const val RATE_LIMIT_MSG_PER_S: Int  = 20
    const val DEFAULT_HOST_PREF_KEY: String = "last_host"
    const val DEFAULT_PORT_PREF_KEY: String = "last_port"
}
