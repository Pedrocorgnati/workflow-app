package com.workflowapp.remote.model

import androidx.compose.ui.graphics.Color
import com.workflowapp.remote.ui.theme.badgeColor
import com.workflowapp.remote.ui.theme.statusColor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for [ConnectionStatus.canTransitionTo], [ConnectionStatus.badgeColor],
 * [PipelineViewState.fromString], and [PipelineViewState.statusColor] — TASK-3/ST005.
 *
 * Note: badgeColor and statusColor are defined in ui/theme/StatusColors.kt.
 */
class StateMachineTest {

    // ===== ConnectionStatus.canTransitionTo =====

    @Test fun `DISCONNECTED to CONNECTING is valid`() {
        assertTrue(ConnectionStatus.DISCONNECTED.canTransitionTo(ConnectionStatus.CONNECTING))
    }

    @Test fun `CONNECTING to CONNECTED is valid`() {
        assertTrue(ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.CONNECTED))
    }

    @Test fun `CONNECTING to RECONNECTING is valid (connection failure path)`() {
        assertTrue(ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.RECONNECTING))
    }

    @Test fun `CONNECTING to DISCONNECTED is invalid and blocked by guard`() {
        assertFalse(ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.DISCONNECTED))
    }

    @Test fun `CONNECTED to DISCONNECTED is valid`() {
        assertTrue(ConnectionStatus.CONNECTED.canTransitionTo(ConnectionStatus.DISCONNECTED))
    }

    @Test fun `CONNECTED to RECONNECTING is valid`() {
        assertTrue(ConnectionStatus.CONNECTED.canTransitionTo(ConnectionStatus.RECONNECTING))
    }

    @Test fun `RECONNECTING to CONNECTING is valid`() {
        assertTrue(ConnectionStatus.RECONNECTING.canTransitionTo(ConnectionStatus.CONNECTING))
    }

    @Test fun `RECONNECTING to DISCONNECTED is valid`() {
        assertTrue(ConnectionStatus.RECONNECTING.canTransitionTo(ConnectionStatus.DISCONNECTED))
    }

    @Test fun `invalid transition does not throw exception`() {
        // Guard returns false — no exception raised
        val result = ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.DISCONNECTED)
        assertFalse(result)
    }

    @Test fun `all key invalid transitions return false`() {
        assertFalse(ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.DISCONNECTED))
        assertFalse(ConnectionStatus.DISCONNECTED.canTransitionTo(ConnectionStatus.CONNECTED))
        assertFalse(ConnectionStatus.DISCONNECTED.canTransitionTo(ConnectionStatus.RECONNECTING))
        assertFalse(ConnectionStatus.CONNECTED.canTransitionTo(ConnectionStatus.CONNECTING))
    }

    // ===== ConnectionStatus.badgeColor =====

    @Test fun `CONNECTED badgeColor is green`() {
        assertEquals(Color(0xFF34D399), ConnectionStatus.CONNECTED.badgeColor)
    }

    @Test fun `RECONNECTING badgeColor is yellow`() {
        assertEquals(Color(0xFFFBBF24), ConnectionStatus.RECONNECTING.badgeColor)
    }

    @Test fun `DISCONNECTED badgeColor is red`() {
        assertEquals(Color(0xFFEF4444), ConnectionStatus.DISCONNECTED.badgeColor)
    }

    @Test fun `CONNECTING badgeColor is info blue`() {
        assertEquals(Color(0xFF38BDF8), ConnectionStatus.CONNECTING.badgeColor)
    }

    // ===== PipelineViewState.fromString =====

    @Test fun `fromString running returns RUNNING`() {
        assertEquals(PipelineViewState.RUNNING, PipelineViewState.fromString("running"))
    }

    @Test fun `fromString paused returns PAUSED`() {
        assertEquals(PipelineViewState.PAUSED, PipelineViewState.fromString("paused"))
    }

    @Test fun `fromString waiting_interaction returns WAITING_INTERACTION`() {
        assertEquals(
            PipelineViewState.WAITING_INTERACTION,
            PipelineViewState.fromString("waiting_interaction")
        )
    }

    @Test fun `fromString completed returns COMPLETED`() {
        assertEquals(PipelineViewState.COMPLETED, PipelineViewState.fromString("completed"))
    }

    @Test fun `fromString failed returns FAILED`() {
        assertEquals(PipelineViewState.FAILED, PipelineViewState.fromString("failed"))
    }

    @Test fun `fromString idle returns IDLE`() {
        assertEquals(PipelineViewState.IDLE, PipelineViewState.fromString("idle"))
    }

    @Test fun `fromString unknown string returns IDLE without crash`() {
        assertEquals(PipelineViewState.IDLE, PipelineViewState.fromString("some_unknown_state"))
    }

    @Test fun `fromString empty string returns IDLE without crash`() {
        assertEquals(PipelineViewState.IDLE, PipelineViewState.fromString(""))
    }

    @Test fun `fromString uppercase RUNNING returns RUNNING (defensive lowercase)`() {
        assertEquals(PipelineViewState.RUNNING, PipelineViewState.fromString("RUNNING"))
    }

    // ===== PipelineViewState.statusColor =====

    @Test fun `FAILED statusColor is red`() {
        assertEquals(Color(0xFFEF4444), PipelineViewState.FAILED.statusColor)
    }

    @Test fun `RUNNING statusColor is green`() {
        assertEquals(Color(0xFF34D399), PipelineViewState.RUNNING.statusColor)
    }

    @Test fun `PAUSED statusColor is yellow`() {
        assertEquals(Color(0xFFFBBF24), PipelineViewState.PAUSED.statusColor)
    }
}
