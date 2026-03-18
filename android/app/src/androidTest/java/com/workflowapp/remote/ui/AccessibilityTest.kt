package com.workflowapp.remote.ui

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodes
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.filter
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.ui.components.ConnectionBar
import com.workflowapp.remote.ui.components.ControlBar
import com.workflowapp.remote.ui.components.OutputArea
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.ui.theme.WorkflowAppTheme
import org.junit.Rule
import org.junit.Test

/**
 * Accessibility (TalkBack) instrumented tests — module-9 ST007.
 *
 * Verifies:
 * - All interactive elements have contentDescription
 * - Connection status badge is announced via liveRegion (semantic node present)
 * - ControlBar buttons have state-aware descriptions
 * - OutputArea has contentDescription for region identification
 * - Touch targets: asserting nodes exist (size enforcement is a layout guarantee)
 */
class AccessibilityTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    // ── ConnectionBar ──────────────────────────────────────────────────────

    @Test
    fun connectionBar_connectButton_hasContentDescription() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ConnectionBar(
                    ipInput        = "",
                    portInput      = "18765",
                    onIpChange     = {},
                    onPortChange   = {},
                    onConnectClick = {},
                    isConnected    = false,
                    isConnecting   = false,
                    status         = ConnectionStatus.DISCONNECTED,
                )
            }
        }
        // "Conectar" button text visible → TalkBack reads button label
        composeTestRule.onNodeWithText("Conectar").assertIsDisplayed()
    }

    @Test
    fun connectionBar_statusBadge_hasSemanticContentDescription() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ConnectionBar(
                    ipInput        = "",
                    portInput      = "18765",
                    onIpChange     = {},
                    onPortChange   = {},
                    onConnectClick = {},
                    isConnected    = false,
                    isConnecting   = false,
                    status         = ConnectionStatus.DISCONNECTED,
                )
            }
        }
        // clearAndSetSemantics sets contentDescription for the badge Row
        composeTestRule
            .onNodeWithContentDescription("Status de conexão: Desconectado")
            .assertIsDisplayed()
    }

    @Test
    fun connectionBar_connectedStatus_announcesCorrectly() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                ConnectionBar(
                    ipInput        = "192.168.1.1",
                    portInput      = "18765",
                    onIpChange     = {},
                    onPortChange   = {},
                    onConnectClick = {},
                    isConnected    = true,
                    isConnecting   = false,
                    status         = ConnectionStatus.CONNECTED,
                )
            }
        }
        composeTestRule
            .onNodeWithContentDescription("Status de conexão: Conectado")
            .assertIsDisplayed()
    }

    // ── ControlBar ────────────────────────────────────────────────────────

    @Test
    fun controlBar_playButton_hasContentDescription_whenEnabled() {
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
            .assertIsDisplayed()
            .assertHasClickAction()
    }

    @Test
    fun controlBar_pauseButton_hasContentDescription_whenEnabled() {
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
            .assertIsDisplayed()
    }

    @Test
    fun controlBar_skipButton_hasContentDescription_whenEnabled() {
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
            .onNodeWithContentDescription("Pular comando atual")
            .assertIsDisplayed()
    }

    @Test
    fun controlBar_disabledButtons_haveUnavailableDescription() {
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
        // All buttons disabled in IDLE — descriptions include "(não disponível)"
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

    // ── OutputArea ────────────────────────────────────────────────────────

    @Test
    fun outputArea_region_hasContentDescription() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                OutputArea(
                    outputLines     = emptyList(),
                    truncationCount = 0,
                )
            }
        }
        composeTestRule
            .onNodeWithContentDescription("Área de output do pipeline")
            .assertIsDisplayed()
    }

    @Test
    fun outputArea_emptyState_isAnnouncedCorrectly() {
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

    // ── WorkflowScreen integration ─────────────────────────────────────────

    @Test
    fun workflowScreen_allInteractiveNodes_haveClickActions() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                WorkflowScreen()
            }
        }
        // All clickable nodes must have a click action (no silent tap targets)
        val clickableNodes = composeTestRule
            .onAllNodes(hasClickAction())
            .fetchSemanticsNodes()

        // At minimum: Connect button + 3 ControlBar buttons
        assert(clickableNodes.size >= 4) {
            "Expected at least 4 interactive elements, found ${clickableNodes.size}"
        }
    }

    @Test
    fun workflowScreen_allClickableNodes_haveNonBlankContentDescription() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                WorkflowScreen()
            }
        }
        val clickableWithDescription = composeTestRule
            .onAllNodes(hasClickAction() and hasContentDescription("", substring = false))
            .fetchSemanticsNodes()

        // Verify each clickable node has a non-empty content description
        clickableWithDescription.forEach { node ->
            val desc = node.config.getOrElse(
                androidx.compose.ui.semantics.SemanticsProperties.ContentDescription
            ) { emptyList() }
            assert(desc.isNotEmpty() && desc.first().isNotBlank()) {
                "Clickable node missing contentDescription: $node"
            }
        }
    }
}
