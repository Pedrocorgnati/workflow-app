package com.workflowapp.remote.connection

import android.content.SharedPreferences
import androidx.annotation.VisibleForTesting
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import com.workflowapp.remote.util.RemoteLogger
import kotlinx.coroutines.launch

/**
 * ConnectionManager — lifecycle-aware reconnect orchestrator for [WebSocketClient].
 *
 * Responsibilities:
 * - Persist and restore connection settings (host, port) via [SharedPreferences].
 * - Schedule exponential backoff reconnects via [BackoffStrategy].
 * - Gate reconnects on network availability via [NetworkMonitor].
 * - Disconnect proactively after [RemoteConstants.BACKGROUND_DISCONNECT_MIN] min
 *   in background (Doze mode friendly) via [DefaultLifecycleObserver].
 * - Reconnect automatically when returning to foreground.
 *
 * @param wsClient       The [WebSocketClient] to manage.
 * @param coroutineScope ViewModel scope — cancelled on ViewModel.onCleared().
 * @param prefs          SharedPreferences for persisting host/port.
 * @param networkMonitor Network availability monitor.
 * @param backoffStrategy Exponential backoff strategy.
 */
class ConnectionManager(
    private val wsClient: WebSocketClient,
    private val coroutineScope: CoroutineScope,
    private val prefs: SharedPreferences,
    private val networkMonitor: NetworkMonitor,
    private val backoffStrategy: BackoffStrategy = BackoffStrategy(),
) : DefaultLifecycleObserver {

    private var backgroundJob: Job? = null
    private var reconnectJob: Job? = null

    @VisibleForTesting
    internal var disconnectedByBackground: Boolean = false

    init {
        // Register on main thread as required by ProcessLifecycleOwner
        try {
            ProcessLifecycleOwner.get().lifecycle.addObserver(this)
            RemoteLogger.d("Registered with ProcessLifecycleOwner")
        } catch (e: Exception) {
            // ProcessLifecycleOwner not available in unit tests — safe to ignore
            RemoteLogger.w("ProcessLifecycleOwner unavailable: ${e.message}")
        }
    }

    // ── DefaultLifecycleObserver ───────────────────────────────────────────────

    /** App came to foreground — cancel background countdown and reconnect if needed. */
    override fun onStart(owner: LifecycleOwner) {
        RemoteLogger.d("App came to foreground — cancelling background countdown")
        backgroundJob?.cancel()
        backgroundJob = null

        if (disconnectedByBackground) {
            disconnectedByBackground = false
            val (host, port) = loadSettings()
            if (host.isNotEmpty()) {
                RemoteLogger.i("Reconnecting after background disconnect")
                wsClient.connect(host, port)
            }
        } else if (!wsClient.isConnected()) {
            // Network may have returned while in background
            val (host, port) = loadSettings()
            if (host.isNotEmpty() && networkMonitor.isCurrentlyAvailable()) {
                RemoteLogger.i("Reconnecting on foreground — previous connection lost")
                wsClient.connect(host, port)
            }
        }
    }

    /** App went to background — schedule proactive disconnect after timeout. */
    override fun onStop(owner: LifecycleOwner) {
        RemoteLogger.d("App went to background — starting ${RemoteConstants.BACKGROUND_DISCONNECT_MIN}min countdown")
        backgroundJob?.cancel()
        backgroundJob = coroutineScope.launch {
            kotlinx.coroutines.delay(RemoteConstants.BACKGROUND_DISCONNECT_MIN * 60_000L)
            if (wsClient.isConnected()) {
                RemoteLogger.i("Background timeout reached — disconnecting proactively")
                disconnectedByBackground = true
                wsClient.disconnect()
            }
        }
    }

    // ── Reconnect logic ───────────────────────────────────────────────────────

    /**
     * Schedule a reconnect attempt with exponential backoff.
     * Called by [WebSocketClient] via the [onScheduleReconnect] callback.
     */
    fun scheduleReconnect() {
        if (!backoffStrategy.shouldRetry()) {
            RemoteLogger.w("Max retry attempts reached — giving up automatic reconnect")
            return
        }

        reconnectJob = backoffStrategy.scheduleRetry(coroutineScope) {
            // Wait for network before attempting — avoids futile connection attempts
            networkMonitor.awaitNetworkAvailable()
            val (host, port) = loadSettings()
            if (host.isNotEmpty()) {
                RemoteLogger.d("Network available — reconnecting to $host:$port")
                wsClient.connect(host, port)
            }
        }
    }

    /**
     * Cancel any pending reconnect job immediately.
     * Called when the user manually edits the IP/port, signalling intent to connect elsewhere.
     */
    fun cancelReconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        RemoteLogger.d("Pending reconnect cancelled by user action")
    }

    /** Reset backoff counters on successful connection. */
    fun resetBackoff() {
        backoffStrategy.reset()
    }

    // ── Settings persistence ──────────────────────────────────────────────────

    /** Persist host and port to SharedPreferences. */
    fun saveSettings(host: String, port: Int) {
        prefs.edit()
            .putString(RemoteConstants.DEFAULT_HOST_PREF_KEY, host)
            .putInt(RemoteConstants.DEFAULT_PORT_PREF_KEY, port)
            .apply()
    }

    /** Load previously persisted connection settings. */
    fun loadSettings(): Pair<String, Int> {
        val host = prefs.getString(RemoteConstants.DEFAULT_HOST_PREF_KEY, "") ?: ""
        val port = prefs.getInt(RemoteConstants.DEFAULT_PORT_PREF_KEY, RemoteConstants.DEFAULT_PORT)
        return host to port
    }

    // ── Cleanup ───────────────────────────────────────────────────────────────

    /** Release all resources. Call from ViewModel.onCleared(). */
    fun cleanup() {
        backgroundJob?.cancel()
        reconnectJob?.cancel()
        try {
            ProcessLifecycleOwner.get().lifecycle.removeObserver(this)
            RemoteLogger.d("Lifecycle observer removed")
        } catch (_: Exception) { /* Not available in tests */ }
        networkMonitor.unregister()
        RemoteLogger.d("ConnectionManager cleaned up")
    }
}
