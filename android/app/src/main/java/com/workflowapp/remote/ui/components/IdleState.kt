package com.workflowapp.remote.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PlayCircleOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.R
import com.workflowapp.remote.model.LastPipelineSummary
import com.workflowapp.remote.ui.theme.AppColors
import java.time.format.DateTimeFormatter

@Composable
fun IdleState(
    lastPipeline: LastPipelineSummary?,
    modifier:     Modifier = Modifier,
) {
    val noActivePipeline = stringResource(R.string.idle_no_pipeline)
    val semanticDesc = if (lastPipeline != null) {
        "$noActivePipeline. ${stringResource(R.string.idle_last_pipeline, lastPipeline.name)}, ${lastPipeline.finalStatus}"
    } else {
        noActivePipeline
    }

    Column(
        modifier              = modifier
            .fillMaxWidth()
            .padding(24.dp)
            .semantics { contentDescription = semanticDesc },
        horizontalAlignment   = Alignment.CenterHorizontally,
        verticalArrangement   = Arrangement.Center,
    ) {
        Icon(
            imageVector        = Icons.Outlined.PlayCircleOutline,
            contentDescription = null,
            modifier           = Modifier.size(64.dp),
            tint               = AppColors.MutedText,
        )
        Spacer(Modifier.size(8.dp))
        Text(
            text  = noActivePipeline,
            style = MaterialTheme.typography.titleMedium,
            color = AppColors.SecondaryText,
        )

        if (lastPipeline != null) {
            Spacer(Modifier.size(4.dp))
            Text(
                text  = stringResource(R.string.idle_last_pipeline, lastPipeline.name),
                style = MaterialTheme.typography.bodySmall,
                color = AppColors.MutedText,
            )
            Text(
                text  = "${lastPipeline.finalStatus} · ${
                    lastPipeline.completedAt.format(
                        DateTimeFormatter.ofPattern("HH:mm dd/MM")
                    )
                }",
                style = MaterialTheme.typography.bodySmall,
                color = AppColors.MutedText,
            )
        }
    }
}
