package com.workflowapp.remote.connection

import androidx.annotation.VisibleForTesting
import timber.log.Timber
import com.workflowapp.remote.model.ConnectionStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "WebSocketClient"

/**
 * WebSocketClient — manages the OkHttp WebSocket connection to the PC remote server.
 *
 * Features:
 * - OkHttp ping every [RemoteConstants.PING_INTERVAL_MS] ms (RFC 6455).
 * - Exposes [state] as [StateFlow] for ViewModel observation.
 * - Automatic reconnect scheduling via [onScheduleReconnect] callback.
 * - Clean disconnect on Doze mode / background lifecycle via [ConnectionManager].
 *
 * Usage (managed by PipelineViewModel via ConnectionManager):
 * ```
 * val client = WebSocketClient(parser, onMessage, onScheduleReconnect)
 * client.connect("100.x.x.x", 18765)
 * client.disconnect()
 * ```
 */
class WebSocketClient(
    private val parser: MessageParser,
    private val onMessage: (WsEnvelope) -> Unit,
    private val onScheduleReconnect: () -> Unit,
) {
    private val _connected = AtomicBoolean(false)
    private var _webSocket: WebSocket? = null
    private var _lastHost: String = ""
    private var _lastPort: Int = RemoteConstants.DEFAULT_PORT

    private val _state = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    /** Observable connection state — collect in ViewModel or UI. */
    val state: StateFlow<ConnectionStatus> = _state.asStateFlow()

    private val _client = OkHttpClient.Builder()
        .pingInterval(RemoteConstants.PING_INTERVAL_MS, TimeUnit.MILLISECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)   // no read timeout for WebSocket
        .connectTimeout(RemoteConstants.CONNECT_TIMEOUT_S, TimeUnit.SECONDS)
        .build()

    // ── Public API ────────────────────────────────────────────────────────────

    /** Open a WebSocket connection to ws://{host}:{port}. */
    fun connect(host: String, port: Int) {
        _lastHost = host
        _lastPort = port
        _state.value = ConnectionStatus.CONNECTING

        val url = "ws://$host:$port"
        val request = Request.Builder().url(url).build()
        Timber.tag(TAG).i("Connecting to $url")
        _webSocket = _client.newWebSocket(request, _listener)
    }

    /** Close the connection cleanly (code 1000). */
    fun disconnect() {
        _webSocket?.close(1000, "User disconnected")
        _webSocket = null
        _connected.set(false)
        _state.value = ConnectionStatus.DISCONNECTED
        Timber.tag(TAG).i("Disconnected (user-initiated)")
    }

    /** True if the WebSocket is currently open. */
    fun isConnected(): Boolean = _connected.get()

    /** Send a pre-serialized JSON string. Returns false if not connected. */
    fun sendRaw(raw: String): Boolean {
        val ws = _webSocket ?: return false
        if (!_connected.get()) return false
        return ws.send(raw)
    }

    /** Expose last connection target for ConnectionManager reconnect logic. */
    fun getLastHost(): String = _lastHost
    fun getLastPort(): Int = _lastPort

    // ── OkHttp WebSocketListener ──────────────────────────────────────────────

    private val _listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            Timber.tag(TAG).i("WebSocket opened")
            _webSocket = webSocket
            _connected.set(true)
            _state.value = ConnectionStatus.CONNECTED
            // Request full snapshot immediately after connecting
            sendRaw(parser.serialize("sync_request"))
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val envelope = parser.parse(text)
            if (envelope == null) {
                Timber.tag(TAG).w("Received unparseable message")
                return
            }
            onMessage(envelope)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Timber.tag(TAG).i("WebSocket closing: code=%d reason=%s", code, reason)
            webSocket.close(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Timber.tag(TAG).i("WebSocket closed: code=%d reason=%s", code, reason)
            _connected.set(false)
            _webSocket = null

            // Normal closure (1000-1003) or policy violation (1008) — do NOT reconnect
            if (code in 1000..1003 || code == 1008) {
                _state.value = ConnectionStatus.DISCONNECTED
            } else {
                _state.value = ConnectionStatus.RECONNECTING
                onScheduleReconnect()
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Timber.tag(TAG).w("WebSocket failure: code=%s error=%s", response?.code, t.message)
            _connected.set(false)
            _webSocket = null

            val code = response?.code ?: -1
            if (code in setOf(1000, 1001, 1002, 1003, 1008)) {
                _state.value = ConnectionStatus.DISCONNECTED
            } else {
                _state.value = ConnectionStatus.RECONNECTING
                onScheduleReconnect()
            }
        }
    }

    // ── Test helpers ──────────────────────────────────────────────────────────

    /** Simulate a successful WebSocket open (for unit tests). */
    @VisibleForTesting
    internal fun simulateOpen(ws: WebSocket) {
        _webSocket = ws
        _connected.set(true)
        _state.value = ConnectionStatus.CONNECTED
    }

    /** Simulate a WebSocket failure (for unit tests). */
    @VisibleForTesting
    internal fun simulateFailure(code: Int, t: Throwable) {
        _connected.set(false)
        _webSocket = null
        if (code in setOf(1000, 1001, 1002, 1003, 1008)) {
            _state.value = ConnectionStatus.DISCONNECTED
        } else {
            _state.value = ConnectionStatus.RECONNECTING
            onScheduleReconnect()
        }
    }

    /** Simulate a WebSocket close (for unit tests). */
    @VisibleForTesting
    internal fun simulateClosed(code: Int, reason: String) {
        _connected.set(false)
        _webSocket = null
        if (code in 1000..1003 || code == 1008) {
            _state.value = ConnectionStatus.DISCONNECTED
        } else {
            _state.value = ConnectionStatus.RECONNECTING
            onScheduleReconnect()
        }
    }
}
