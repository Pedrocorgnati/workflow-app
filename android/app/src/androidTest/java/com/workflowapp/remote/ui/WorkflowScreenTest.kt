package com.workflowapp.remote.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.ui.theme.WorkflowAppTheme
import org.junit.Rule
import org.junit.Test

/**
 * UI tests for WorkflowScreen.
 * TODO: Expand after /auto-flow execute populates ViewModel with real logic.
 */
class WorkflowScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun workflowScreen_showsConnectionBar() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                WorkflowScreen()
            }
        }

        // ConnectionBar IP field is always visible
        composeTestRule
            .onNodeWithText("IP")
            .assertIsDisplayed()
    }

    @Test
    fun workflowScreen_showsControlBar() {
        composeTestRule.setContent {
            WorkflowAppTheme {
                WorkflowScreen()
            }
        }

        composeTestRule
            .onNodeWithContentDescription("Iniciar pipeline (não disponível)")
            .assertIsDisplayed()
    }
}
