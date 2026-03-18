package com.workflowapp.remote.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.workflowapp.remote.model.CommandItem
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.ui.components.CommandQueueList
import com.workflowapp.remote.ui.components.ControlBar
import com.workflowapp.remote.ui.components.InteractionCard
import com.workflowapp.remote.ui.components.OutputArea
import com.workflowapp.remote.ui.theme.WorkflowAppTheme
import org.junit.Rule
import org.junit.Test

// ─────────────────────────────────────────────────────────────────────────────
// CommandQueueList tests
// ─────────────────────────────────────────────────────────────────────────────

class CommandQueueListTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun commandQueueList_showsDisconnectedPlaceholder_whenNotConnected() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                CommandQueueList(
                    commands          = emptyList(),
                    activeIndex       = -1,
                    isConnected       = false,
                    lastPipeline      = null,
                    onCommandSelected = {},
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Desconectado")
            .assertIsDisplayed()
    }

    @Test
    fun commandQueueList_showsCommands_whenConnectedWithCommands() {
        val commands = listOf(
            CommandItem(index = 0, name = "echo hello", status = "RUNNING"),
            CommandItem(index = 1, name = "ls -la",     status = "PENDING"),
        )

        composeTestRule.setContent {
            WorkflowAppTheme {
                CommandQueueList(
                    commands          = commands,
                    activeIndex       = 0,
                    isConnected       = true,
                    lastPipeline      = null,
                    onCommandSelected = {},
                )
            }
        }

        composeTestRule.onNodeWithText("echo hello").assertIsDisplayed()
        composeTestRule.onNodeWithText("ls -la").assertIsDisplayed()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// OutputArea tests
// ─────────────────────────────────────────────────────────────────────────────

class OutputAreaTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun outputArea_showsEmptyPlaceholder_whenNoOutput() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                OutputArea(
                    outputLines     = emptyList(),
                    truncationCount = 0,
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Aguardando output")
            .assertIsDisplayed()
    }

    @Test
    fun outputArea_showsLines_whenOutputPresent() {
        val lines = listOf("Line 1", "Line 2", "Line 3")

        composeTestRule.setContent {
            WorkflowAppTheme {
                OutputArea(
                    outputLines     = lines,
                    truncationCount = 0,
                )
            }
        }

        composeTestRule.onNodeWithText("Line 1").assertIsDisplayed()
    }

    @Test
    fun outputArea_showsTruncationNotice_whenTruncated() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                OutputArea(
                    outputLines     = listOf("current line"),
                    truncationCount = 500,
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("500 linhas omitidas")
            .assertIsDisplayed()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// InteractionCard tests
// ─────────────────────────────────────────────────────────────────────────────

class InteractionCardTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun interactionCard_isHidden_whenInteractionIsNull() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                InteractionCard(
                    interaction    = null,
                    onSendResponse = { _, _ -> },
                    onDismiss      = {},
                )
            }
        }

        composeTestRule
            .onNodeWithTag("InteractionCard")
            .assertDoesNotExist()
    }

    @Test
    fun interactionCard_showsPrompt_whenInteractionNotNull() {
        val interaction = InteractionRequestMsg(
            messageId = "req-001",
            prompt    = "Continuar com a tarefa?",
            type      = "yes_no",
            options   = listOf("yes", "no"),
        )

        composeTestRule.setContent {
            WorkflowAppTheme {
                InteractionCard(
                    interaction    = interaction,
                    onSendResponse = { _, _ -> },
                    onDismiss      = {},
                )
            }
        }

        composeTestRule
            .onNodeWithText("Continuar com a tarefa?")
            .assertIsDisplayed()
    }

    @Test
    fun interactionCard_sendButtonDisabled_whenResponseBlank() {
        val interaction = InteractionRequestMsg(messageId = "r1", prompt = "Prompt?", type = "yes_no", options = emptyList())

        composeTestRule.setContent {
            WorkflowAppTheme {
                InteractionCard(
                    interaction    = interaction,
                    onSendResponse = { _, _ -> },
                    onDismiss      = {},
                )
            }
        }

        composeTestRule
            .onNodeWithText("Enviar")
            .assertIsNotEnabled()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// ControlBar tests
// ─────────────────────────────────────────────────────────────────────────────

class ControlBarTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun controlBar_playEnabled_whenPaused() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ControlBar(
                    state   = PipelineViewState.PAUSED,
                    onPlay  = {},
                    onPause = {},
                    onSkip  = {},
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Iniciar pipeline")
            .assertIsEnabled()
    }

    @Test
    fun controlBar_pauseEnabled_whenRunning() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ControlBar(
                    state   = PipelineViewState.RUNNING,
                    onPlay  = {},
                    onPause = {},
                    onSkip  = {},
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Pausar pipeline")
            .assertIsEnabled()
    }

    @Test
    fun controlBar_allDisabled_whenIdle() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ControlBar(
                    state   = PipelineViewState.IDLE,
                    onPlay  = {},
                    onPause = {},
                    onSkip  = {},
                )
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Iniciar pipeline (não disponível)")
            .assertIsDisplayed()
        composeTestRule
            .onNodeWithContentDescription("Pausar pipeline (não disponível)")
            .assertIsDisplayed()
        composeTestRule
            .onNodeWithContentDescription("Pular comando atual (não disponível)")
            .assertIsDisplayed()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// IdleState tests
// ─────────────────────────────────────────────────────────────────────────────

class IdleStateTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun idleState_showsPlaceholderText() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                com.workflowapp.remote.ui.components.IdleState(lastPipeline = null)
            }
        }

        composeTestRule
            .onNodeWithText("Nenhum pipeline ativo")
            .assertIsDisplayed()
    }
}
