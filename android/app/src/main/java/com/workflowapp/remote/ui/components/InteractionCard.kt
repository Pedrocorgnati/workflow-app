package com.workflowapp.remote.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.R
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.ResponseType
import com.workflowapp.remote.ui.theme.AppColors
import kotlinx.coroutines.delay

@Composable
fun InteractionCard(
    interaction:    InteractionRequestMsg?,
    onSendResponse: (String, ResponseType) -> Unit,
    onDismiss:      () -> Unit,
    modifier:       Modifier = Modifier,
) {
    var responseText by remember { mutableStateOf("") }
    val focusRequester = remember { FocusRequester() }

    // Clear input when interaction closes
    LaunchedEffect(interaction) {
        if (interaction == null) responseText = ""
    }

    // Auto-focus text field after animation completes (300ms delay).
    // Key is the full interaction object (not just null-ness) so a second interaction
    // that replaces the first while the card is still visible also triggers re-focus.
    LaunchedEffect(interaction) {
        if (interaction != null) {
            delay(300L)
            runCatching { focusRequester.requestFocus() }
        }
    }

    AnimatedVisibility(
        visible = interaction != null,
        enter   = slideInVertically(initialOffsetY = { it }) + fadeIn(tween(200)),
        exit    = slideOutVertically(targetOffsetY = { it }) + fadeOut(tween(150)),
        modifier = modifier,
    ) {
        Card(
            modifier  = Modifier
                .fillMaxWidth()
                .padding(8.dp)
                .testTag("InteractionCard"),
            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
            colors    = CardDefaults.cardColors(containerColor = AppColors.ElevatedSurface),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {

                // Prompt text
                Text(
                    text  = interaction?.prompt ?: "",
                    style = MaterialTheme.typography.titleSmall,
                    color = AppColors.OnSurface,
                )

                Spacer(Modifier.height(8.dp))

                // Free-text response field
                OutlinedTextField(
                    value         = responseText,
                    onValueChange = { responseText = it },
                    label         = { Text(stringResource(R.string.interaction_response_label)) },
                    maxLines      = 3,
                    modifier      = Modifier
                        .fillMaxWidth()
                        .focusRequester(focusRequester),
                )

                Spacer(Modifier.height(8.dp))

                // Quick-response chips
                QuickResponseRow { type ->
                    onSendResponse("", type)
                    responseText = ""
                }

                Spacer(Modifier.height(4.dp))

                // Send button (disabled when field is blank)
                Button(
                    onClick = {
                        if (responseText.isNotBlank()) {
                            onSendResponse(responseText, ResponseType.TEXT)
                            responseText = ""
                        }
                    },
                    enabled  = responseText.isNotBlank(),
                    colors   = ButtonDefaults.buttonColors(
                        containerColor = AppColors.PrimaryAmber,
                        contentColor   = AppColors.OnPrimary,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(R.string.interaction_send))
                }
            }
        }
    }
}

@Composable
private fun QuickResponseRow(
    onQuickResponse: (ResponseType) -> Unit,
) {
    val buttons = listOf(
        stringResource(R.string.interaction_quick_ok)     to ResponseType.YES,
        stringResource(R.string.interaction_quick_yes)    to ResponseType.YES,
        stringResource(R.string.interaction_quick_no)     to ResponseType.NO,
        stringResource(R.string.interaction_quick_cancel) to ResponseType.CANCEL,
    )

    Row(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp)) {
        buttons.forEach { (label, type) ->
            OutlinedButton(
                onClick  = { onQuickResponse(type) },
                modifier = Modifier
                    .weight(1f)
                    .defaultMinSize(minHeight = 48.dp),
                contentPadding = PaddingValues(4.dp),
            ) {
                Text(label, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
