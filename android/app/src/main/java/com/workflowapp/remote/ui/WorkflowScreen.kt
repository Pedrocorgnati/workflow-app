package com.workflowapp.remote.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.traversalIndex
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.model.ControlAction
import com.workflowapp.remote.ui.components.CommandQueueList
import com.workflowapp.remote.ui.components.ConnectionBar
import com.workflowapp.remote.ui.components.ControlBar
import com.workflowapp.remote.ui.components.FeedbackMessage
import com.workflowapp.remote.ui.components.FeedbackSnackbarHost
import com.workflowapp.remote.ui.components.IdleState
import com.workflowapp.remote.ui.components.InteractionCard
import com.workflowapp.remote.ui.components.OutputArea
import com.workflowapp.remote.ui.components.toSnackbarSpec
import com.workflowapp.remote.viewmodel.PipelineViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

@Composable
fun WorkflowScreen(
    viewModel: PipelineViewModel = viewModel(),
) {
    // ── Collect state ──────────────────────────────────────────────────────
    val connectionStatus     by viewModel.connectionStatus.collectAsStateWithLifecycle()
    val commandQueue         by viewModel.commandQueue.collectAsStateWithLifecycle()
    val activeIndex          by viewModel.activeCommandIndex.collectAsStateWithLifecycle()
    val currentOutput        by viewModel.currentOutput.collectAsStateWithLifecycle()
    val pendingInteraction   by viewModel.pendingInteraction.collectAsStateWithLifecycle()
    val pipelineState        by viewModel.pipelineState.collectAsStateWithLifecycle()
    val ipInput              by viewModel.ipInput.collectAsStateWithLifecycle()
    val portInput            by viewModel.portInput.collectAsStateWithLifecycle()
    val truncationCount      by viewModel.truncationCount.collectAsStateWithLifecycle()
    val lastPipeline         by viewModel.lastPipeline.collectAsStateWithLifecycle()
    val ipValidationError    by viewModel.ipValidationError.collectAsStateWithLifecycle()
    val portValidationError  by viewModel.portValidationError.collectAsStateWithLifecycle()

    // ── Snackbar ───────────────────────────────────────────────────────────
    val snackbarHostState = remember { SnackbarHostState() }
    val scope             = rememberCoroutineScope()

    // Holder for the Indefinite "Reconectando..." snackbar job.
    // Using a stable object reference so it survives recompositions.
    val reconnectingHolder = remember { object { var job: Job? = null } }

    // Collect error events → show snackbar
    LaunchedEffect(Unit) {
        viewModel.errorEvent.collect { message ->
            scope.launch {
                snackbarHostState.showSnackbar(message, duration = SnackbarDuration.Short)
            }
        }
    }

    // Collect typed feedback events → dispatch to snackbar with correct duration.
    // FeedbackMessage.Reconnecting uses Indefinite duration and is tracked via
    // reconnectingHolder.job so it can be cancelled when the connection recovers.
    LaunchedEffect(Unit) {
        viewModel.feedbackEvents.collect { feedback ->
            when (feedback) {
                FeedbackMessage.Reconnecting -> {
                    // Cancel previous reconnecting snackbar (if any) before showing new one
                    reconnectingHolder.job?.cancel()
                    reconnectingHolder.job = scope.launch {
                        val (message, duration) = feedback.toSnackbarSpec()
                        snackbarHostState.showSnackbar(message, duration = duration)
                    }
                }
                else -> {
                    // Any non-Reconnecting event dismisses the reconnecting snackbar first
                    reconnectingHolder.job?.cancel()
                    reconnectingHolder.job = null
                    val (message, duration) = feedback.toSnackbarSpec()
                    scope.launch {
                        snackbarHostState.showSnackbar(message, duration = duration)
                    }
                }
            }
        }
    }

    // Dismiss the "Reconectando..." snackbar when connection is re-established
    LaunchedEffect(connectionStatus) {
        if (connectionStatus == ConnectionStatus.CONNECTED) {
            reconnectingHolder.job?.cancel()
            reconnectingHolder.job = null
        }
    }

    // ── Layout ─────────────────────────────────────────────────────────────
    Scaffold(
        bottomBar    = {
            ControlBar(
                state   = pipelineState,
                onPlay  = { viewModel.sendControl(ControlAction.PLAY) },
                onPause = { viewModel.sendControl(ControlAction.PAUSE) },
                onSkip  = { viewModel.sendControl(ControlAction.SKIP) },
            )
        },
        snackbarHost = { FeedbackSnackbarHost(snackbarHostState) },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
        ) {
            // ConnectionBar (traversalIndex = 0)
            ConnectionBar(
                ipInput             = ipInput,
                portInput           = portInput,
                onIpChange          = viewModel::updateIp,
                onPortChange        = viewModel::updatePort,
                onConnectClick      = viewModel::toggleConnection,
                isConnected         = connectionStatus == ConnectionStatus.CONNECTED,
                isConnecting        = connectionStatus == ConnectionStatus.CONNECTING,
                status              = connectionStatus,
                ipValidationError   = ipValidationError,
                portValidationError = portValidationError,
                modifier            = Modifier.semantics { traversalIndex = 0f },
            )

            // CommandQueueList / IdleState / DisconnectedPlaceholder (traversalIndex = 1)
            AnimatedContent(
                targetState  = commandQueue.isEmpty() && connectionStatus == ConnectionStatus.CONNECTED,
                transitionSpec = { fadeIn(tween(300)) togetherWith fadeOut(tween(200)) },
                label        = "commandListTransition",
                modifier     = Modifier.weight(0.35f).semantics {
                    traversalIndex = 1f
                    contentDescription = "Fila de comandos"
                    heading()
                },
            ) { isIdle ->
                if (isIdle) {
                    IdleState(lastPipeline = lastPipeline)
                } else {
                    CommandQueueList(
                        commands          = commandQueue,
                        activeIndex       = activeIndex,
                        isConnected       = connectionStatus == ConnectionStatus.CONNECTED,
                        lastPipeline      = lastPipeline,
                        onCommandSelected = viewModel::selectCommand,
                    )
                }
            }

            // OutputArea (traversalIndex = 2)
            OutputArea(
                outputLines     = currentOutput,
                truncationCount = truncationCount,
                modifier        = Modifier.weight(0.65f).semantics { traversalIndex = 2f },
            )

            // InteractionCard (traversalIndex = 3 — conditional)
            AnimatedVisibility(visible = pendingInteraction != null) {
                InteractionCard(
                    interaction    = pendingInteraction,
                    onSendResponse = viewModel::sendInteractionResponse,
                    onDismiss      = viewModel::dismissInteraction,
                    modifier       = Modifier.semantics { traversalIndex = 3f },
                )
            }
        }
    }
}
