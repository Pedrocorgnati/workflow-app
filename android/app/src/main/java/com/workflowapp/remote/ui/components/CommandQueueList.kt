package com.workflowapp.remote.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateColorAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.model.CommandItem
import com.workflowapp.remote.model.LastPipelineSummary
import com.workflowapp.remote.ui.theme.AppColors

@Composable
fun CommandQueueList(
    commands:          List<CommandItem>,
    activeIndex:       Int,
    isConnected:       Boolean,
    lastPipeline:      LastPipelineSummary?,
    onCommandSelected: (Int) -> Unit,
    modifier:          Modifier = Modifier,
) {
    when {
        commands.isEmpty() && isConnected ->
            IdleState(lastPipeline = lastPipeline, modifier = modifier)

        commands.isEmpty() ->
            DisconnectedPlaceholder(modifier = modifier)

        else -> LazyColumn(
            modifier = modifier.fillMaxWidth(),
        ) {
            itemsIndexed(
                items = commands,
                key   = { _, item -> item.index },
            ) { index, command ->
                CommandItemRow(
                    command  = command,
                    isActive = index == activeIndex,
                    onClick  = { onCommandSelected(index) },
                )
            }
        }
    }
}

@Composable
private fun CommandItemRow(
    command:  CommandItem,
    isActive: Boolean,
    onClick:  () -> Unit,
) {
    val (textColor, iconVec, textDecoration) = when (command.status) {
        "running"   -> Triple(AppColors.PrimaryAmber, Icons.Default.PlayArrow,              null)
        "completed" -> Triple(AppColors.Success,      Icons.Default.CheckCircle,            null)
        "failed"    -> Triple(
            MaterialTheme.colorScheme.error,           Icons.Default.Error,                 null
        )
        "skipped"   -> Triple(AppColors.MutedText,    Icons.Default.SkipNext,
            TextDecoration.LineThrough)
        else        -> Triple(AppColors.SecondaryText, Icons.Default.RadioButtonUnchecked,  null)
    }

    val animatedTextColor by animateColorAsState(
        targetValue = textColor,
        label       = "itemColor",
    )

    val infiniteTransition = rememberInfiniteTransition(label = "runningPulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue  = 0.6f,
        targetValue   = 1.0f,
        animationSpec = infiniteRepeatable(
            animation  = tween(600, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulseAlpha",
    )

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(
                onClick      = onClick,
                onClickLabel = "Ver output do comando",
            )
            .background(
                color = if (isActive) AppColors.ElevatedSurface else Color.Transparent
            )
            .border(
                width  = if (isActive) 2.dp else 0.dp,
                color  = if (isActive) AppColors.PrimaryAmber else Color.Transparent,
                shape  = RoundedCornerShape(4.dp),
            )
            .padding(horizontal = 12.dp, vertical = 8.dp)
            .defaultMinSize(minHeight = 48.dp)
            .testTag("CommandItem")
            .semantics {
                val statusLabel = when (command.status) {
                    "running"   -> "em execução"
                    "completed" -> "concluído"
                    "failed"    -> "falhou"
                    "skipped"   -> "pulado"
                    "acked"     -> "reconhecido"
                    "rejected"  -> "rejeitado"
                    else        -> command.status
                }
                contentDescription = "${command.name}, $statusLabel"
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector        = iconVec,
            contentDescription = null, // semantics on Row
            tint               = animatedTextColor,
            modifier           = Modifier
                .size(20.dp)
                .alpha(if (command.status == "running") pulseAlpha else 1f),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text           = command.name,
            color          = animatedTextColor,
            textDecoration = textDecoration,
            style          = MaterialTheme.typography.bodyMedium,
            modifier       = Modifier.weight(1f),
        )
    }
}

@Composable
fun DisconnectedPlaceholder(modifier: Modifier = Modifier) {
    Column(
        modifier              = modifier
            .fillMaxWidth()
            .padding(24.dp)
            .semantics { contentDescription = "Desconectado do servidor" },
        horizontalAlignment   = Alignment.CenterHorizontally,
        verticalArrangement   = Arrangement.Center,
    ) {
        Icon(
            imageVector        = Icons.Outlined.WifiOff,
            contentDescription = null,
            modifier           = Modifier.size(48.dp),
            tint               = AppColors.MutedText,
        )
        Spacer(modifier = Modifier.size(8.dp))
        Text(
            text      = "Conecte ao servidor para ver o pipeline",
            style     = MaterialTheme.typography.bodyMedium,
            color     = AppColors.MutedText,
            textAlign = TextAlign.Center,
        )
    }
}
