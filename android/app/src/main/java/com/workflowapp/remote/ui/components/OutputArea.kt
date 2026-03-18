package com.workflowapp.remote.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.Divider
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.workflowapp.remote.R
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.workflowapp.remote.ui.theme.AppColors
import kotlinx.coroutines.launch

@Composable
fun OutputArea(
    outputLines:     List<String>,
    truncationCount: Int,
    modifier:        Modifier = Modifier,
) {
    val listState      = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()

    val isAtBottom by remember {
        derivedStateOf {
            val info        = listState.layoutInfo
            val lastVisible = info.visibleItemsInfo.lastOrNull()?.index ?: -1
            lastVisible >= info.totalItemsCount - 1
        }
    }

    var autoScrollEnabled by remember { mutableStateOf(true) }

    LaunchedEffect(isAtBottom) {
        if (isAtBottom) autoScrollEnabled = true
    }

    LaunchedEffect(listState.isScrollInProgress) {
        if (listState.isScrollInProgress && !isAtBottom) {
            autoScrollEnabled = false
        }
    }

    LaunchedEffect(outputLines.size) {
        if (autoScrollEnabled && outputLines.isNotEmpty()) {
            coroutineScope.launch {
                listState.animateScrollToItem(outputLines.size - 1)
            }
        }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .semantics {
                contentDescription = "Área de output do pipeline"
                heading()
            },
    ) {
        AnimatedContent(
            targetState  = outputLines.isEmpty(),
            transitionSpec = { fadeIn(tween(300)) togetherWith fadeOut(tween(200)) },
            label        = "outputTransition",
        ) { isEmpty ->
            if (isEmpty) {
                EmptyOutputPlaceholder()
            } else {
                SelectionContainer {
                    LazyColumn(
                        state    = listState,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 8.dp)
                            .pointerInput(Unit) {
                                detectTapGestures { autoScrollEnabled = false }
                            },
                    ) {
                        if (truncationCount > 0) {
                            item(key = "truncation") {
                                TruncationNotice(linesOmitted = truncationCount)
                            }
                        }
                        itemsIndexed(
                            items = outputLines,
                            key   = { index, _ -> index },
                        ) { _, line ->
                            Text(
                                text       = line,
                                fontFamily = FontFamily.Monospace,
                                style      = MaterialTheme.typography.bodySmall,
                                color      = AppColors.OnSurface,
                                modifier   = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                }
            }
        }

        // FAB "Voltar ao final" — visible when auto-scroll is paused
        AnimatedVisibility(
            visible = !autoScrollEnabled,
            enter   = fadeIn(tween(200)),
            exit    = fadeOut(tween(150)),
            modifier = Modifier.align(Alignment.BottomEnd),
        ) {
            FloatingActionButton(
                onClick = {
                    if (outputLines.isNotEmpty()) {
                        coroutineScope.launch {
                            listState.animateScrollToItem(outputLines.size - 1)
                        }
                    }
                    autoScrollEnabled = true
                },
                modifier       = Modifier
                    .padding(8.dp)
                    .size(48.dp),
                containerColor = AppColors.Surface,
            ) {
                Icon(
                    imageVector        = Icons.Outlined.Terminal,
                    contentDescription = "Voltar ao final do output",
                    tint               = AppColors.PrimaryAmber,
                )
            }
        }
    }
}

@Composable
private fun EmptyOutputPlaceholder() {
    Box(
        modifier          = Modifier.fillMaxSize(),
        contentAlignment  = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier            = Modifier.semantics {
                contentDescription = "Aguardando output"
            },
        ) {
            Icon(
                imageVector        = Icons.Outlined.Terminal,
                contentDescription = null,
                modifier           = Modifier.size(32.dp),
                tint               = AppColors.MutedText,
            )
            Text(
                text  = stringResource(R.string.output_waiting),
                style = MaterialTheme.typography.bodyMedium,
                color = AppColors.MutedText,
            )
        }
    }
}

@Composable
fun TruncationNotice(
    linesOmitted: Int,
    modifier:     Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .semantics { contentDescription = "$linesOmitted linhas omitidas" },
    ) {
        Divider(color = AppColors.Warning.copy(alpha = 0.3f), thickness = 0.5.dp)
        Text(
            text      = "— $linesOmitted linhas omitidas —",
            style     = MaterialTheme.typography.bodySmall,
            color     = AppColors.Warning,
            textAlign = TextAlign.Center,
            modifier  = Modifier
                .fillMaxWidth()
                .padding(vertical = 4.dp),
        )
        Divider(color = AppColors.Warning.copy(alpha = 0.3f), thickness = 0.5.dp)
    }
}
