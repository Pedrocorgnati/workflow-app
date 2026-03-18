package com.workflowapp.remote.ui.components

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

// ── Typed feedback events ───────────────────────────────────────────────────

/**
 * Typed UX feedback events emitted by PipelineViewModel.
 * Collected in WorkflowScreen and rendered via [FeedbackSnackbarHost].
 */
sealed class FeedbackMessage {
    /** WebSocket connection failed; auto-reconnect will start. */
    data object ConnectionFailed : FeedbackMessage()
    /** User's interaction response was sent successfully. */
    data object ResponseSent : FeedbackMessage()
    /** PC responded to interaction before Android user could. */
    data object ResponseConsumedByPC : FeedbackMessage()
    /** Active reconnect attempt in progress. */
    data object Reconnecting : FeedbackMessage()
}

/**
 * Maps a [FeedbackMessage] to a (message text, duration) pair for Snackbar display.
 */
fun FeedbackMessage.toSnackbarSpec(): Pair<String, SnackbarDuration> = when (this) {
    FeedbackMessage.ConnectionFailed      -> "Não foi possível conectar. Verifique IP e porta." to SnackbarDuration.Long
    FeedbackMessage.ResponseSent          -> "Resposta enviada" to SnackbarDuration.Short
    FeedbackMessage.ResponseConsumedByPC  -> "Já respondido pelo PC" to SnackbarDuration.Short
    FeedbackMessage.Reconnecting          -> "Reconectando..." to SnackbarDuration.Indefinite
}

// ── Snackbar host ───────────────────────────────────────────────────────────

/**
 * Custom Snackbar host that applies the Graphite Amber D19 styling.
 * Position is managed by Scaffold (automatically above the ControlBar bottomBar).
 */
@Composable
fun FeedbackSnackbarHost(snackbarHostState: SnackbarHostState) {
    SnackbarHost(snackbarHostState) { data ->
        Snackbar(
            snackbarData   = data,
            containerColor = MaterialTheme.colorScheme.inverseSurface,
            contentColor   = MaterialTheme.colorScheme.inverseOnSurface,
            shape          = RoundedCornerShape(8.dp),
        )
    }
}
