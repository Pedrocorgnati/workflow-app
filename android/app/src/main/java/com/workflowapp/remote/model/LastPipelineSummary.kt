package com.workflowapp.remote.model

import java.time.LocalDateTime

data class LastPipelineSummary(
    val name:        String,
    val finalStatus: String,
    val completedAt: LocalDateTime,
)
