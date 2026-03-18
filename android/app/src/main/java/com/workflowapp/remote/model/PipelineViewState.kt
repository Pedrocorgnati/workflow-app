package com.workflowapp.remote.model

import timber.log.Timber

/**
 * View-layer enum that mirrors the PC pipeline state machine.
 *
 * Uses [fromString] to map server-side lowercase strings to enum values with
 * defensive lowercase() handling and a safe IDLE fallback for unknown states.
 *
 * Colors are hardcoded temporarily.
 * TODO module-8: Replace hardcoded colors with MaterialTheme.colorScheme tokens.
 */
enum class PipelineViewState {
    IDLE,
    RUNNING,
    PAUSED,
    COMPLETED,
    FAILED,
    CANCELLED,
    WAITING_INTERACTION,
    INTERACTIVE_MODE;

    companion object {
        /**
         * Maps server-side status strings to [PipelineViewState].
         * Falls back to [IDLE] for unknown strings (with log warning).
         * Uses [String.lowercase] defensively — protocol specifies lowercase but client is tolerant.
         */
        fun fromString(status: String): PipelineViewState = when (status.lowercase()) {
            "idle"                 -> IDLE
            "running"              -> RUNNING
            "paused"               -> PAUSED
            "completed"            -> COMPLETED
            "failed"               -> FAILED
            "cancelled"            -> CANCELLED
            "waiting_interaction"  -> WAITING_INTERACTION
            "interactive"          -> INTERACTIVE_MODE
            else -> {
                Timber.tag("PipelineViewState").w("Unknown status '%s' — defaulting to IDLE", status)
                IDLE
            }
        }
    }
}

// UI color extensions moved to ui/theme/StatusColors.kt to preserve model layer purity.
