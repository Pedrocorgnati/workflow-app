package com.workflowapp.remote.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateColorAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.R
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.ui.theme.AppColors

@Composable
fun ConnectionBar(
    ipInput:             String,
    portInput:           String,
    onIpChange:          (String) -> Unit,
    onPortChange:        (String) -> Unit,
    onConnectClick:      () -> Unit,
    isConnected:         Boolean,
    isConnecting:        Boolean,
    status:              ConnectionStatus,
    ipValidationError:   String?  = null,
    portValidationError: String?  = null,
    modifier:            Modifier = Modifier,
) {
    val fieldsEnabled = !isConnected && !isConnecting

    Row(
        modifier              = modifier
            .fillMaxWidth()
            .background(AppColors.Surface)
            .padding(horizontal = 8.dp, vertical = 8.dp)
            .semantics {
                contentDescription = "Conexão com servidor"
                heading()
            },
        verticalAlignment     = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Campo IP
        OutlinedTextField(
            value         = ipInput,
            onValueChange = onIpChange,
            label         = { Text(stringResource(R.string.connection_ip_label)) },
            placeholder   = { Text(stringResource(R.string.connection_ip_placeholder)) },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction    = ImeAction.Next,
            ),
            isError    = ipValidationError != null,
            supportingText = ipValidationError?.let { err -> { Text(err) } },
            modifier   = Modifier
                .weight(1f)
                .defaultMinSize(minHeight = 48.dp),
            enabled    = fieldsEnabled,
            singleLine = true,
        )

        // Campo Porta
        OutlinedTextField(
            value         = portInput,
            onValueChange = onPortChange,
            label         = { Text(stringResource(R.string.connection_port_label)) },
            placeholder   = { Text(stringResource(R.string.connection_port_placeholder)) },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Number,
                imeAction    = ImeAction.Done,
            ),
            keyboardActions = KeyboardActions(
                onDone = { if (fieldsEnabled) onConnectClick() }
            ),
            isError    = portValidationError != null,
            supportingText = portValidationError?.let { err -> { Text(err) } },
            modifier   = Modifier
                .width(80.dp)
                .defaultMinSize(minHeight = 48.dp),
            enabled    = fieldsEnabled,
            singleLine = true,
        )

        // Botão Conectar / Desconectar
        Button(
            onClick  = onConnectClick,
            enabled  = !isConnecting,
            colors   = ButtonDefaults.buttonColors(
                containerColor = AppColors.PrimaryAmber,
                contentColor   = AppColors.OnPrimary,
            ),
            modifier = Modifier
                .defaultMinSize(minHeight = 48.dp),
        ) {
            if (isConnecting) {
                CircularProgressIndicator(
                    modifier    = Modifier.size(16.dp),
                    color       = AppColors.OnPrimary,
                    strokeWidth = 2.dp,
                )
                Spacer(Modifier.width(8.dp))
            }
            Text(
                text = when {
                    isConnected  -> stringResource(R.string.connection_btn_disconnect)
                    isConnecting -> stringResource(R.string.connection_btn_connecting)
                    else         -> stringResource(R.string.connection_btn_connect)
                }
            )
        }

        // Badge de status
        ConnectionStatusBadge(status = status)
    }
}

@Composable
fun ConnectionStatusBadge(
    status:   ConnectionStatus,
    modifier: Modifier = Modifier,
) {
    val badgeColor by animateColorAsState(
        targetValue = when (status) {
            ConnectionStatus.CONNECTED     -> AppColors.Success
            ConnectionStatus.RECONNECTING  -> AppColors.Warning
            ConnectionStatus.CONNECTING    -> AppColors.Info
            ConnectionStatus.DISCONNECTED  -> MaterialTheme.colorScheme.error
        },
        label = "badgeColor",
    )

    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue  = 0.4f,
        targetValue   = 1.0f,
        animationSpec = infiniteRepeatable(
            animation  = tween(600, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "badgeAlpha",
    )

    val effectiveAlpha  = if (status == ConnectionStatus.RECONNECTING) pulseAlpha else 1f
    val statusLabel     = when (status) {
        ConnectionStatus.CONNECTED     -> stringResource(R.string.connection_status_connected)
        ConnectionStatus.RECONNECTING  -> stringResource(R.string.connection_status_reconnecting)
        ConnectionStatus.CONNECTING    -> stringResource(R.string.connection_status_connecting)
        ConnectionStatus.DISCONNECTED  -> stringResource(R.string.connection_status_disconnected)
    }

    Row(
        verticalAlignment     = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        modifier              = modifier.clearAndSetSemantics {
            liveRegion = LiveRegionMode.Polite
            contentDescription = "Status de conexão: $statusLabel"
        },
    ) {
        Box(
            modifier = Modifier
                .size(12.dp)
                .alpha(effectiveAlpha)
                .background(color = badgeColor, shape = CircleShape)
        )
        Text(
            text  = statusLabel,
            style = MaterialTheme.typography.bodySmall,
            color = AppColors.SecondaryText,
        )
    }
}
