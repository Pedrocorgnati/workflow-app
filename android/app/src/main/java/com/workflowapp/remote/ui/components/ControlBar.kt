package com.workflowapp.remote.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.traversalIndex
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.ui.theme.AppColors

@Composable
fun ControlBar(
    state:   PipelineViewState,
    onPlay:  () -> Unit,
    onPause: () -> Unit,
    onSkip:  () -> Unit,
    modifier: Modifier = Modifier,
) {
    val canPlay  = state in listOf(PipelineViewState.PAUSED)
    val canPause = state == PipelineViewState.RUNNING
    val canSkip  = state in listOf(PipelineViewState.RUNNING, PipelineViewState.WAITING_INTERACTION)

    Row(
        modifier              = modifier
            .fillMaxWidth()
            .background(AppColors.Surface)
            .padding(8.dp)
            .semantics { traversalIndex = 4f },
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment     = Alignment.CenterVertically,
    ) {
        ControlButton(
            icon               = Icons.Default.PlayArrow,
            contentDescription = if (canPlay) "Iniciar pipeline" else "Iniciar pipeline (não disponível)",
            enabled            = canPlay,
            onClick            = onPlay,
        )
        ControlButton(
            icon               = Icons.Default.Pause,
            contentDescription = if (canPause) "Pausar pipeline" else "Pausar pipeline (não disponível)",
            enabled            = canPause,
            onClick            = onPause,
        )
        ControlButton(
            icon               = Icons.Default.SkipNext,
            contentDescription = if (canSkip) "Pular comando atual" else "Pular comando atual (não disponível)",
            enabled            = canSkip,
            onClick            = onSkip,
        )
    }
}

@Composable
private fun ControlButton(
    icon:               ImageVector,
    contentDescription: String,
    enabled:            Boolean,
    onClick:            () -> Unit,
) {
    IconButton(
        onClick  = onClick,
        enabled  = enabled,
        modifier = Modifier
            .size(48.dp)
            .alpha(if (enabled) 1f else 0.38f),
    ) {
        Icon(
            imageVector        = icon,
            contentDescription = contentDescription,
            tint               = if (enabled) AppColors.PrimaryAmber else AppColors.MutedText,
            modifier           = Modifier.size(24.dp),
        )
    }
}
