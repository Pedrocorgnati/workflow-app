package com.workflowapp.remote.model

/**
 * State machine for the WebSocket connection lifecycle.
 *
 * Valid transitions (enforced by [canTransitionTo]):
 * - DISCONNECTED → CONNECTING   ✓  (user initiates connection)
 * - CONNECTING   → CONNECTED    ✓  (handshake succeeded)
 * - CONNECTING   → RECONNECTING ✓  (connection attempt failed immediately)
 * - CONNECTED    → DISCONNECTED ✓  (user or server closes cleanly)
 * - CONNECTED    → RECONNECTING ✓  (connection lost unexpectedly)
 * - RECONNECTING → CONNECTING   ✓  (backoff retry attempt)
 * - RECONNECTING → DISCONNECTED ✓  (max retries exceeded or user cancels)
 * All other combinations return false from [canTransitionTo].
 */
enum class ConnectionStatus(val label: String) {
    DISCONNECTED("Desconectado"),
    CONNECTING("Conectando"),
    CONNECTED("Conectado"),
    RECONNECTING("Reconectando");

    /**
     * Returns true if a transition from this state to [next] is permitted.
     *
     * Invalid transitions (e.g. CONNECTING → DISCONNECTED) are blocked to prevent
     * the UI from showing DISCONNECTED without having passed through CONNECTED.
     * The ViewModel logs a warning and ignores the transition instead of throwing.
     */
    fun canTransitionTo(next: ConnectionStatus): Boolean = when (this) {
        DISCONNECTED -> next == CONNECTING
        CONNECTING   -> next == CONNECTED || next == RECONNECTING
        CONNECTED    -> next == DISCONNECTED || next == RECONNECTING
        RECONNECTING -> next == CONNECTING || next == DISCONNECTED
    }
}

// UI color extensions moved to ui/theme/StatusColors.kt to preserve model layer purity.
