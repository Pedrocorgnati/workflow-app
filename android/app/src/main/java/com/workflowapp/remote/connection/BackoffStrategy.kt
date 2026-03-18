package com.workflowapp.remote.connection

import com.workflowapp.remote.util.RemoteLogger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.min
import kotlin.random.Random


/**
 * BackoffStrategy — exponential backoff with jitter for WebSocket reconnect scheduling.
 *
 * Sequence: 2s → 4s → 8s → … capped at [RemoteConstants.MAX_BACKOFF_S] seconds.
 * Each interval includes up to 500ms of random jitter to prevent thundering herd.
 *
 * Call [reset] after a successful connection to restart the sequence.
 */
class BackoffStrategy {
    private var attemptCount: Int = 0
    private val maxAttempts: Int = RemoteConstants.MAX_RETRY_ATTEMPTS
    private var currentDelayMs: Long = RemoteConstants.INITIAL_BACKOFF_S * 1000L

    /** Returns true if another retry should be attempted. */
    fun shouldRetry(): Boolean = attemptCount < maxAttempts

    /**
     * Calculates the next delay with exponential growth and jitter.
     * Side effect: increments [attemptCount] and doubles [currentDelayMs].
     *
     * @return delay in milliseconds (capped at MAX_BACKOFF_S * 1000 + 500ms jitter)
     */
    fun nextDelayMs(): Long {
        val baseDelay = min(currentDelayMs, RemoteConstants.MAX_BACKOFF_S * 1000L)
        val jitter = Random.nextLong(0, RemoteConstants.MAX_JITTER_MS)
        val delay = baseDelay + jitter
        currentDelayMs *= 2
        attemptCount++
        return delay
    }

    /**
     * Resets the backoff to its initial state.
     * Call this after a successful connection.
     */
    fun reset() {
        attemptCount = 0
        currentDelayMs = RemoteConstants.INITIAL_BACKOFF_S * 1000L
        RemoteLogger.d("Reset — ready for fresh retry sequence")
    }

    /**
     * Schedules [block] after the next calculated delay within [scope].
     * Returns the launched [Job] so callers can cancel the pending retry,
     * or `null` if max retries have been reached.
     */
    fun scheduleRetry(scope: CoroutineScope, block: suspend () -> Unit): Job? {
        if (!shouldRetry()) {
            RemoteLogger.w("Max retries reached — not scheduling more")
            return null
        }
        val delayMs = nextDelayMs()
        RemoteLogger.d("Scheduling retry in ${delayMs}ms (attempt $attemptCount/$maxAttempts)")
        return scope.launch {
            delay(delayMs)
            block()
        }
    }
}
