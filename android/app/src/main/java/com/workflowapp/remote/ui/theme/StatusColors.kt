package com.workflowapp.remote.ui.theme

import androidx.compose.ui.graphics.Color
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.model.PipelineViewState

/**
 * UI color extensions for [ConnectionStatus] and [PipelineViewState].
 *
 * Kept separate from the model layer to preserve Clean Architecture layering:
 * model must not depend on Compose UI.
 *
 * TODO module-8: Replace hardcoded colors with MaterialTheme.colorScheme tokens.
 * Example: ConnectionStatus.CONNECTED → MaterialTheme.colorScheme.tertiary
 */

/** Badge color for each connection status. */
val ConnectionStatus.badgeColor: Color
    get() = when (this) {
        ConnectionStatus.CONNECTED    -> Color(0xFF34D399)  // green
        ConnectionStatus.RECONNECTING -> Color(0xFFFBBF24)  // yellow
        ConnectionStatus.CONNECTING   -> Color(0xFF38BDF8)  // info blue
        ConnectionStatus.DISCONNECTED -> Color(0xFFEF4444)  // red
    }

/** Status color for each pipeline state. */
val PipelineViewState.statusColor: Color
    get() = when (this) {
        PipelineViewState.RUNNING             -> Color(0xFF34D399)  // green
        PipelineViewState.PAUSED              -> Color(0xFFFBBF24)  // yellow
        PipelineViewState.WAITING_INTERACTION -> Color(0xFFFBBF24)  // yellow
        PipelineViewState.INTERACTIVE_MODE    -> Color(0xFFFBBF24)  // yellow
        PipelineViewState.FAILED              -> Color(0xFFEF4444)  // red
        PipelineViewState.COMPLETED           -> Color(0xFF38BDF8)  // blue
        PipelineViewState.CANCELLED           -> Color(0xFF94A3B8)  // slate
        PipelineViewState.IDLE                -> Color(0xFF94A3B8)  // slate neutral
    }
