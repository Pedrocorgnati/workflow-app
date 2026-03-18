package com.workflowapp.remote.model

/**
 * Represents a single command in the pipeline queue.
 *
 * status values: "pending" | "running" | "completed" | "failed" | "skipped" | "acked" | "rejected"
 */
data class CommandItem(
    val index:  Int,
    val name:   String,
    val status: String,
)
