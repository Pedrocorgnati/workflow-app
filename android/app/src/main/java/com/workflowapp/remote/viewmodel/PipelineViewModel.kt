package com.workflowapp.remote.viewmodel

import android.app.Application
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import androidx.annotation.VisibleForTesting
import timber.log.Timber
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.CreationExtras
import androidx.lifecycle.viewModelScope
import com.workflowapp.remote.connection.BackoffStrategy
import com.workflowapp.remote.connection.ConnectionManager
import com.workflowapp.remote.connection.MessageParser
import com.workflowapp.remote.connection.NetworkMonitor
import com.workflowapp.remote.connection.RemoteConstants
import com.workflowapp.remote.connection.WebSocketClient
import com.workflowapp.remote.connection.WsEnvelope
import com.workflowapp.remote.model.CommandItem
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.model.LastPipelineSummary
import com.workflowapp.remote.model.ControlAckMsg
import com.workflowapp.remote.model.ControlAction
import com.workflowapp.remote.model.ErrorMsg
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.InteractiveModeEndedMsg
import com.workflowapp.remote.model.OutputChunkMsg
import com.workflowapp.remote.model.OutputTruncatedMsg
import com.workflowapp.remote.model.PipelineStateMsg
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.data.ConnectionPreferences
import com.workflowapp.remote.data.isValidIp
import com.workflowapp.remote.data.isValidPort
import com.workflowapp.remote.model.RemoteMessage
import com.workflowapp.remote.model.ResponseType
import com.workflowapp.remote.ui.components.FeedbackMessage
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val TAG = "PipelineViewModel"

/**
 * PipelineViewModel — manages UI state for the workflow remote screen.
 *
 * Wires [WebSocketClient] (OkHttp) + [ConnectionManager] (lifecycle/reconnect)
 * + [NetworkMonitor] + [BackoffStrategy] into a reactive ViewModel.
 *
 * State machine guards:
 * - All [connectionStatus] changes go through [transitionConnectionStatus] which applies
 *   [ConnectionStatus.canTransitionTo] guards — invalid transitions are logged and ignored.
 *
 * Outbound messages:
 * - Queued via a [Channel.BUFFERED] to preserve FIFO order and avoid blocking the UI thread.
 * - [sendControl] has a 1-second debounce to prevent double-tap spam.
 * - PLAY → RESUME substitution when pipeline is [PipelineViewState.PAUSED].
 *
 * Interaction responses:
 * - [sendInteractionResponse] uses optimistic update (clears [pendingInteraction] immediately)
 *   with rollback if the outbound channel is closed.
 */
class PipelineViewModel(
    app: Application,
    private val savedStateHandle: SavedStateHandle,
) : AndroidViewModel(app) {

    // ── Infrastructure ─────────────────────────────────────────────────────

    private val prefs = try {
        val masterKey = MasterKey.Builder(app)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            app,
            "remote_settings_encrypted",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (_: Exception) {
        // Fallback for environments where Keystore is unavailable (e.g. older emulators)
        app.getSharedPreferences("remote_settings", android.content.Context.MODE_PRIVATE)
    }
    internal val connectionPreferences = ConnectionPreferences(app)
    internal val parser = MessageParser()
    internal val networkMonitor = NetworkMonitor(app)

    internal val wsClient = WebSocketClient(
        parser = parser,
        onMessage = { envelope ->
            val message = parser.parseMessage(envelope)
            if (message != null) handleMessage(message)
        },
        onScheduleReconnect = { connectionManager.scheduleReconnect() },
    )

    internal val connectionManager = ConnectionManager(
        wsClient = wsClient,
        coroutineScope = viewModelScope,
        prefs = prefs,
        networkMonitor = networkMonitor,
        backoffStrategy = BackoffStrategy(),
    )

    /** Outbound message queue — FIFO, non-blocking for the UI thread. */
    internal val outboundChannel = Channel<String>(Channel.BUFFERED)

    /** Debounce job for [sendControl] — cancels previous job on each new call. */
    private var controlDebounceJob: Job? = null

    // ── Connection state (guarded by canTransitionTo) ─────────────────────

    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus: StateFlow<ConnectionStatus> = _connectionStatus.asStateFlow()

    private val _ipInput = MutableStateFlow("")
    val ipInput: StateFlow<String> = _ipInput.asStateFlow()

    private val _portInput  = MutableStateFlow(RemoteConstants.DEFAULT_PORT.toString())
    val portInput: StateFlow<String>  = _portInput.asStateFlow()

    /** Non-null when IP field contains an invalid address (shown as field error). */
    private val _ipValidationError = MutableStateFlow<String?>(null)
    val ipValidationError: StateFlow<String?> = _ipValidationError.asStateFlow()

    /** Non-null when port field contains an out-of-range value (shown as field error). */
    private val _portValidationError = MutableStateFlow<String?>(null)
    val portValidationError: StateFlow<String?> = _portValidationError.asStateFlow()

    // ── Pipeline state ──────────────────────────────────────────────────────

    private val _pipelineState = MutableStateFlow(PipelineViewState.IDLE)
    val pipelineState: StateFlow<PipelineViewState> = _pipelineState.asStateFlow()

    private val _commandQueue = MutableStateFlow<List<CommandItem>>(emptyList())
    val commandQueue: StateFlow<List<CommandItem>> = _commandQueue.asStateFlow()

    private val _activeCommandIndex = MutableStateFlow(-1)
    val activeCommandIndex: StateFlow<Int> = _activeCommandIndex.asStateFlow()

    // ── Output ─────────────────────────────────────────────────────────────

    private val _currentOutput = MutableStateFlow<List<String>>(emptyList())
    val currentOutput: StateFlow<List<String>> = _currentOutput.asStateFlow()

    // ── Interaction ────────────────────────────────────────────────────────

    private val _pendingInteraction = MutableStateFlow<InteractionRequestMsg?>(null)
    val pendingInteraction: StateFlow<InteractionRequestMsg?> = _pendingInteraction.asStateFlow()

    // ── Output truncation counter ──────────────────────────────────────────

    private val _truncationCount = MutableStateFlow(0)
    val truncationCount: StateFlow<Int> = _truncationCount.asStateFlow()

    // ── Last completed pipeline summary ───────────────────────────────────

    private val _lastPipeline = MutableStateFlow<LastPipelineSummary?>(null)
    val lastPipeline: StateFlow<LastPipelineSummary?> = _lastPipeline.asStateFlow()

    // ── Events (one-shot) ─────────────────────────────────────────────────

    private val _errorEvent = MutableSharedFlow<String>()
    val errorEvent: SharedFlow<String> = _errorEvent.asSharedFlow()

    /** Emitted when the PC responds to an interaction before the Android user does. */
    private val _interactiveModeEndedEvent = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val interactiveModeEndedEvent: SharedFlow<Unit> = _interactiveModeEndedEvent.asSharedFlow()

    /**
     * Typed UX feedback events — collected by WorkflowScreen for Snackbar rendering.
     * Buffer of 8 prevents drop on rapid emissions during reconnect cycles.
     */
    private val _feedbackEvents = MutableSharedFlow<FeedbackMessage>(extraBufferCapacity = 8)
    val feedbackEvents: SharedFlow<FeedbackMessage> = _feedbackEvents.asSharedFlow()

    // ── Init ───────────────────────────────────────────────────────────────

    init {
        networkMonitor.register()

        // Restore connection settings — priority: SavedStateHandle > ConnectionPreferences > legacy prefs
        // SavedStateHandle preserves uncommitted form text across process death (e.g. user typed IP but hadn't connected yet)
        val savedIp   = savedStateHandle.get<String>(KEY_IP_INPUT)
        val savedPort = savedStateHandle.get<String>(KEY_PORT_INPUT)
        if (savedIp != null) {
            _ipInput.value   = savedIp
            _portInput.value = savedPort ?: RemoteConstants.DEFAULT_PORT.toString()
        } else {
            val lastIp   = connectionPreferences.loadIp()
            val lastPort = connectionPreferences.loadPort()
            if (lastIp.isNotEmpty()) {
                _ipInput.value   = lastIp
                _portInput.value = lastPort.toString()
            } else {
                // Fallback: legacy connectionManager prefs
                val (legacyHost, legacyPort) = connectionManager.loadSettings()
                if (legacyHost.isNotEmpty()) {
                    _ipInput.value   = legacyHost
                    _portInput.value = legacyPort.toString()
                }
            }
        }

        // Collect wsClient state changes through the guard + handle CONNECTED side-effects
        viewModelScope.launch {
            wsClient.state.collect { status ->
                transitionConnectionStatus(status)
                if (status == ConnectionStatus.CONNECTED) {
                    connectionManager.resetBackoff()
                    val ip   = _ipInput.value.trim()
                    val port = _portInput.value.trim().toIntOrNull() ?: RemoteConstants.DEFAULT_PORT
                    connectionPreferences.save(ip, port)
                }
            }
        }

        // Outbound consumer loop — processes queued messages in FIFO order
        viewModelScope.launch {
            for (msg in outboundChannel) {
                val sent = wsClient.sendRaw(msg)
                if (!sent) {
                    Timber.tag(TAG).w("Message dropped — not connected")
                }
            }
        }

        // Cancel pending reconnect when user changes the IP (intent to connect elsewhere)
        viewModelScope.launch {
            _ipInput.drop(1).collect {
                connectionManager.cancelReconnect()
            }
        }
    }

    // ── State machine guard ────────────────────────────────────────────────

    /**
     * Safe state transition for [connectionStatus].
     * All changes to [_connectionStatus] MUST go through this function.
     * Direct assignment is forbidden — use this method to enforce [canTransitionTo] guards.
     */
    private fun transitionConnectionStatus(next: ConnectionStatus) {
        val current = _connectionStatus.value
        if (current.canTransitionTo(next)) {
            _connectionStatus.value = next
            Timber.tag(TAG).d("Connection: %s → %s", current, next)
            // Emit typed feedback for UX-relevant transitions
            when {
                next == ConnectionStatus.RECONNECTING -> viewModelScope.launch {
                    _feedbackEvents.emit(FeedbackMessage.Reconnecting)
                }
                current == ConnectionStatus.RECONNECTING && next == ConnectionStatus.DISCONNECTED -> viewModelScope.launch {
                    _feedbackEvents.emit(FeedbackMessage.ConnectionFailed)
                }
            }
        } else {
            Timber.tag(TAG).w("Invalid connection transition %s → %s — ignored", current, next)
        }
    }

    // ── Inbound message handling ───────────────────────────────────────────

    /**
     * Process a typed [RemoteMessage] from the server and update the appropriate StateFlow.
     * The `when` is exhaustive — the compiler enforces all [RemoteMessage] subtypes are handled.
     */
    fun handleMessage(message: RemoteMessage) {
        when (message) {
            is PipelineStateMsg -> {
                val newState = PipelineViewState.fromString(message.status)
                _pipelineState.value = newState
                _commandQueue.value = message.commandQueue
                // Store summary when pipeline reaches a terminal state
                if (newState in TERMINAL_STATES) {
                    val pipelineName = message.commandQueue.firstOrNull()?.name ?: "Pipeline"
                    _lastPipeline.value = LastPipelineSummary(
                        name        = pipelineName,
                        finalStatus = newState.name.lowercase()
                            .replaceFirstChar { it.uppercase() },
                        completedAt = java.time.LocalDateTime.now(),
                    )
                }
            }
            is OutputChunkMsg -> {
                _currentOutput.value = (_currentOutput.value + message.lines)
                    .takeLast(RemoteConstants.MAX_BUFFER_LINES)
                // New output chunk after truncation — reset notice
                if (_truncationCount.value > 0) _truncationCount.value = 0
            }
            is OutputTruncatedMsg -> {
                _truncationCount.value = message.linesOmitted
                viewModelScope.launch {
                    _errorEvent.emit("Output truncado: ${message.linesOmitted} linhas omitidas")
                }
            }
            is InteractionRequestMsg -> {
                _pendingInteraction.value = message
            }
            is InteractiveModeEndedMsg -> {
                // If there was a pending interaction, PC responded first (first-response-wins)
                if (_pendingInteraction.value != null) {
                    viewModelScope.launch {
                        _interactiveModeEndedEvent.emit(Unit)
                        _feedbackEvents.emit(FeedbackMessage.ResponseConsumedByPC)
                    }
                }
                _pendingInteraction.value = null
            }
            is ErrorMsg -> {
                viewModelScope.launch {
                    _errorEvent.emit(message.error)
                }
            }
            is ControlAckMsg -> {
                val updated = _commandQueue.value.map { cmd ->
                    if (cmd.index == message.action.toIntOrNull()) {
                        cmd.copy(status = if (message.accepted) "acked" else "rejected")
                    } else cmd
                }
                _commandQueue.value = updated
            }
        }
    }

    // ── Actions ────────────────────────────────────────────────────────────

    fun updateIp(ip: String) {
        _ipInput.value = ip
        savedStateHandle[KEY_IP_INPUT] = ip
        _ipValidationError.value = when {
            ip.isBlank()     -> null  // empty field — no error, user may still be typing
            !isValidIp(ip)   -> "Endereço IP inválido"
            else             -> null
        }
    }

    fun updatePort(port: String) {
        _portInput.value = port
        savedStateHandle[KEY_PORT_INPUT] = port
        val portInt = port.toIntOrNull()
        _portValidationError.value = when {
            port.isBlank()                       -> null
            portInt == null                      -> "Porta deve ser um número"
            !isValidPort(portInt)                -> "Porta fora do intervalo (1024–65535)"
            else                                 -> null
        }
    }

    fun toggleConnection() {
        when (connectionStatus.value) {
            ConnectionStatus.CONNECTED,
            ConnectionStatus.CONNECTING,
            ConnectionStatus.RECONNECTING -> {
                wsClient.disconnect()
            }
            ConnectionStatus.DISCONNECTED -> {
                val host = _ipInput.value.trim()
                val port = _portInput.value.trim().toIntOrNull() ?: RemoteConstants.DEFAULT_PORT
                when {
                    host.isEmpty() -> {
                        Timber.tag(TAG).w("toggleConnection() called with empty host")
                        _ipValidationError.value = "Informe o endereço IP do servidor"
                        viewModelScope.launch {
                            _errorEvent.emit("IP vazio — informe o endereço do servidor")
                        }
                    }
                    !isValidIp(host) -> {
                        Timber.tag(TAG).w("toggleConnection() called with invalid IP")
                        _ipValidationError.value = "Endereço IP inválido"
                    }
                    !isValidPort(port) -> {
                        Timber.tag(TAG).w("toggleConnection() called with invalid port")
                        _portValidationError.value = "Porta fora do intervalo (1024–65535)"
                    }
                    else -> {
                        connectionManager.saveSettings(host, port)
                        wsClient.connect(host, port)
                    }
                }
            }
        }
    }

    /**
     * Send a control command with 1-second debounce.
     *
     * If [action] is [ControlAction.PLAY] and the pipeline is [PipelineViewState.PAUSED],
     * the actual command sent is [ControlAction.RESUME] (Python's play-vs-resume logic).
     *
     * Each call cancels any pending debounce job, so rapid taps result in only the last
     * command being sent (after 1 second of inactivity).
     */
    fun sendControl(action: ControlAction) {
        controlDebounceJob?.cancel()
        controlDebounceJob = viewModelScope.launch {
            delay(RemoteConstants.CONTROL_DEBOUNCE_MS)
            val actualAction = if (
                action == ControlAction.PLAY &&
                _pipelineState.value == PipelineViewState.PAUSED
            ) {
                ControlAction.RESUME
            } else {
                action
            }
            val envelope = parser.serialize("control", mapOf("action" to actualAction.value))
            val result = outboundChannel.trySend(envelope)
            if (result.isFailure) {
                Timber.tag(TAG).w("sendControl: channel full or closed — command dropped")
            }
        }
    }

    /**
     * Send a response to a pending interaction request.
     *
     * Uses optimistic update: [pendingInteraction] is cleared immediately for instant UI feedback.
     * If the outbound channel is closed or full, the original value is restored (rollback).
     */
    fun sendInteractionResponse(text: String, type: ResponseType) {
        val saved = _pendingInteraction.value
        _pendingInteraction.value = null  // optimistic update

        val envelope = parser.serialize(
            "interaction_response",
            mapOf("text" to text, "type" to type.value),
        )
        val result = outboundChannel.trySend(envelope)

        if (result.isFailure) {
            // Rollback optimistic update
            _pendingInteraction.value = saved
            viewModelScope.launch {
                _errorEvent.emit("Falha ao enviar resposta — tente novamente")
            }
            Timber.tag(TAG).e("sendInteractionResponse: channel closed or full")
        } else {
            viewModelScope.launch {
                _feedbackEvents.emit(FeedbackMessage.ResponseSent)
            }
        }
    }

    fun dismissInteraction() {
        _pendingInteraction.value = null
    }

    fun selectCommand(index: Int) {
        _activeCommandIndex.value = index
    }

    // ── Cleanup ────────────────────────────────────────────────────────────

    override fun onCleared() {
        super.onCleared()
        wsClient.disconnect()
        connectionManager.cleanup()
        outboundChannel.close()
        Timber.tag(TAG).i("ViewModel cleared — WebSocket disconnected, channel closed")
    }

    // ── Test helpers ───────────────────────────────────────────────────────

    /** Exposes onCleared() for unit tests. */
    @VisibleForTesting
    internal fun clearForTest() = onCleared()

    @VisibleForTesting
    internal val outboundChannelForTest: Channel<String>
        get() = outboundChannel

    // ── Factory ────────────────────────────────────────────────────────────

    companion object {
        private const val KEY_IP_INPUT   = "ip_input"
        private const val KEY_PORT_INPUT = "port_input"

        /** Pipeline states that produce a [LastPipelineSummary] upon arrival. */
        private val TERMINAL_STATES = setOf(
            PipelineViewState.COMPLETED,
            PipelineViewState.FAILED,
            PipelineViewState.CANCELLED,
        )

        /**
         * Factory for creating [PipelineViewModel] with [SavedStateHandle] injection.
         *
         * Uses [CreationExtras] API (Lifecycle 2.5+) so the system provides a
         * properly scoped [SavedStateHandle] that survives process death.
         *
         * Usage in Activity/Composable:
         * ```kotlin
         * val viewModel: PipelineViewModel by viewModels { PipelineViewModel.Factory }
         * // or in Compose:
         * val viewModel = viewModel<PipelineViewModel>(factory = PipelineViewModel.Factory)
         * ```
         */
        val Factory: ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(
                modelClass: Class<T>,
                extras: CreationExtras,
            ): T {
                val app = extras[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]!!
                val savedStateHandle = extras.createSavedStateHandle()
                return PipelineViewModel(app, savedStateHandle) as T
            }
        }
    }
}
