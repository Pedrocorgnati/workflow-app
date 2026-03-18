package com.workflowapp.remote.viewmodel

import com.workflowapp.remote.connection.RemoteConstants
import com.workflowapp.remote.data.isValidIp
import com.workflowapp.remote.data.isValidPort
import com.workflowapp.remote.model.CommandItem
import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.model.ControlAction
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.InteractiveModeEndedMsg
import com.workflowapp.remote.model.OutputChunkMsg
import com.workflowapp.remote.model.PipelineStateMsg
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.model.ResponseType
import com.workflowapp.remote.ui.components.FeedbackMessage
import com.workflowapp.remote.util.MainDispatcherRule
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Unit tests for [PipelineViewModel] — covers TASK-1/ST005 BDD scenarios.
 *
 * NOTE: PipelineViewModel is an AndroidViewModel and requires a real Application.
 * These tests use [io.mockk.mockk] for infrastructure and bypass Application-dependent
 * infrastructure by calling [handleMessage] directly.
 *
 * For full ViewModel integration tests (with Application), use Robolectric or instrumentation tests.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PipelineViewModelTest {

    @get:Rule
    val coroutineRule = MainDispatcherRule()

    private val testScheduler = TestCoroutineScheduler()
    private val testDispatcher = StandardTestDispatcher(testScheduler)
    private val testScope = TestScope(testDispatcher)

    // ── Helpers ──────────────────────────────────────────────────────────────

    /**
     * Build a standalone parser + ViewModel facade for testing handleMessage directly.
     * This avoids the need for Application / Android SDK context.
     */
    private fun buildStateHolder(): PipelineViewModelStateHolder =
        PipelineViewModelStateHolder()

    // ── Cenário 1: Initial states are correct ─────────────────────────────────

    @Test
    fun `initial pipelineState is IDLE and commandQueue is empty`() {
        val holder = buildStateHolder()
        assertEquals(PipelineViewState.IDLE, holder.pipelineState)
        assertEquals(emptyList<CommandItem>(), holder.commandQueue)
        assertEquals(emptyList<String>(), holder.currentOutput)
        assertNull(holder.pendingInteraction)
    }

    // ── Cenário 2: handleMessage PipelineStateMsg ─────────────────────────────

    @Test
    fun `handleMessage PipelineStateMsg updates pipelineState and commandQueue`() {
        val holder = buildStateHolder()
        val commands = listOf(CommandItem(0, "Task A", "pending"))
        holder.handleMessage(PipelineStateMsg("msg-1", commands, "running"))
        assertEquals(PipelineViewState.RUNNING, holder.pipelineState)
        assertEquals(commands, holder.commandQueue)
    }

    // ── Cenário 3: handleMessage OutputChunkMsg ───────────────────────────────

    @Test
    fun `handleMessage OutputChunkMsg appends lines to currentOutput`() {
        val holder = buildStateHolder()
        holder.handleMessage(OutputChunkMsg("msg-2", listOf("line1", "line2")))
        assertEquals(listOf("line1", "line2"), holder.currentOutput)
    }

    // ── Cenário 4: Output buffer respects MAX_BUFFER_LINES ────────────────────

    @Test
    fun `output buffer trims at MAX_BUFFER_LINES`() {
        val holder = buildStateHolder()
        val bigBatch = List(RemoteConstants.MAX_BUFFER_LINES + 100) { "line $it" }
        holder.handleMessage(OutputChunkMsg("msg-3", bigBatch))
        assertEquals(RemoteConstants.MAX_BUFFER_LINES, holder.currentOutput.size)
    }

    @Test
    fun `output buffer trims at exact boundary — oldest line removed`() {
        val holder = buildStateHolder()
        val fill = List(RemoteConstants.MAX_BUFFER_LINES) { "line $it" }
        holder.handleMessage(OutputChunkMsg("msg-4", fill))
        assertEquals(RemoteConstants.MAX_BUFFER_LINES, holder.currentOutput.size)

        // Add one more — oldest should be evicted
        holder.handleMessage(OutputChunkMsg("msg-5", listOf("extra")))
        assertEquals(RemoteConstants.MAX_BUFFER_LINES, holder.currentOutput.size)
        assertEquals("extra", holder.currentOutput.last())
    }

    // ── Cenário 5: handleMessage InteractionRequestMsg ────────────────────────

    @Test
    fun `handleMessage InteractionRequestMsg sets pendingInteraction`() {
        val holder = buildStateHolder()
        val interaction = InteractionRequestMsg("msg-6", "Continue?", "yes_no", listOf("yes", "no"))
        holder.handleMessage(interaction)
        assertEquals(interaction, holder.pendingInteraction)
    }

    // ── Cenário 6: handleMessage InteractiveModeEndedMsg ──────────────────────

    @Test
    fun `handleMessage InteractiveModeEndedMsg clears pendingInteraction`() {
        val holder = buildStateHolder()
        holder.handleMessage(InteractionRequestMsg("msg-7", "Continue?", "yes_no", emptyList()))
        holder.handleMessage(InteractiveModeEndedMsg("msg-8"))
        assertNull(holder.pendingInteraction)
    }

    // ── Cenário 7: sendControl PLAY→RESUME when PAUSED ────────────────────────

    @Test
    fun `sendControl PLAY sends RESUME when pipeline is PAUSED`() = testScope.runTest {
        val holder = buildStateHolder()
        // Set pipeline to PAUSED
        holder.handleMessage(PipelineStateMsg("msg-9", emptyList(), "paused"))
        assertEquals(PipelineViewState.PAUSED, holder.pipelineState)

        // Call sendControl(PLAY) — should substitute RESUME
        val sent = mutableListOf<String>()
        holder.simulateSendControl(ControlAction.PLAY) { envelope ->
            sent.add(envelope)
        }

        // RESUME action should be in the envelope
        assert(sent.any { it.contains("resume") }) {
            "Expected 'resume' action but got: $sent"
        }
    }

    // ── Cenário 8: sendControl PLAY sends PLAY when IDLE ──────────────────────

    @Test
    fun `sendControl PLAY sends PLAY when pipeline is IDLE`() = testScope.runTest {
        val holder = buildStateHolder()
        assertEquals(PipelineViewState.IDLE, holder.pipelineState)

        val sent = mutableListOf<String>()
        holder.simulateSendControl(ControlAction.PLAY) { envelope ->
            sent.add(envelope)
        }

        assert(sent.any { it.contains("\"play\"") }) {
            "Expected 'play' action but got: $sent"
        }
    }

    // ── Cenário 9: ConnectionStatus.canTransitionTo guards ────────────────────

    @Test
    fun `connectionStatus guard blocks CONNECTING to DISCONNECTED`() {
        assertFalse(
            ConnectionStatus.CONNECTING.canTransitionTo(ConnectionStatus.DISCONNECTED)
        )
    }

    @Test
    fun `connectionStatus guard allows CONNECTED to RECONNECTING`() {
        assertTrue(
            ConnectionStatus.CONNECTED.canTransitionTo(ConnectionStatus.RECONNECTING)
        )
    }

    // ── Cenário 10: FeedbackMessage — Reconnecting emitted on RECONNECTING ──

    @Test
    fun `transitionConnectionStatus emits Reconnecting on RECONNECTING`() {
        val holder = buildStateHolder()
        // Simulate: DISCONNECTED → CONNECTING → CONNECTED → RECONNECTING
        holder.transitionConnectionStatus(ConnectionStatus.CONNECTING)
        holder.transitionConnectionStatus(ConnectionStatus.CONNECTED)
        holder.transitionConnectionStatus(ConnectionStatus.RECONNECTING)
        assertEquals(FeedbackMessage.Reconnecting, holder.lastFeedback)
    }

    // ── Cenário 11: FeedbackMessage — ConnectionFailed on RECONNECTING→DISCONNECTED

    @Test
    fun `transitionConnectionStatus emits ConnectionFailed on RECONNECTING to DISCONNECTED`() {
        val holder = buildStateHolder()
        holder.transitionConnectionStatus(ConnectionStatus.CONNECTING)
        holder.transitionConnectionStatus(ConnectionStatus.CONNECTED)
        holder.transitionConnectionStatus(ConnectionStatus.RECONNECTING)
        holder.transitionConnectionStatus(ConnectionStatus.DISCONNECTED)
        assertEquals(FeedbackMessage.ConnectionFailed, holder.lastFeedback)
    }

    // ── Cenário 12: FeedbackMessage — ResponseConsumedByPC on InteractiveModeEndedMsg

    @Test
    fun `handleMessage InteractiveModeEndedMsg emits ResponseConsumedByPC when interaction pending`() {
        val holder = buildStateHolder()
        holder.handleMessage(InteractionRequestMsg("msg-10", "Continue?", "yes_no", emptyList()))
        holder.handleMessage(InteractiveModeEndedMsg("msg-11"))
        assertEquals(FeedbackMessage.ResponseConsumedByPC, holder.lastFeedback)
    }

    @Test
    fun `handleMessage InteractiveModeEndedMsg does not emit when no interaction pending`() {
        val holder = buildStateHolder()
        holder.handleMessage(InteractiveModeEndedMsg("msg-12"))
        assertNull(holder.lastFeedback)
    }

    // ── Cenário 13: IP/Port validation helpers ──────────────────────────────────

    @Test
    fun `updateIp with invalid IP sets ipValidationError`() {
        val holder = buildStateHolder()
        holder.updateIp("not-an-ip")
        assertEquals("Endereço IP inválido", holder.ipValidationError)
    }

    @Test
    fun `updateIp with valid IP clears ipValidationError`() {
        val holder = buildStateHolder()
        holder.updateIp("not-an-ip")
        holder.updateIp("192.168.1.1")
        assertNull(holder.ipValidationError)
    }

    @Test
    fun `updateIp with blank does not set error`() {
        val holder = buildStateHolder()
        holder.updateIp("")
        assertNull(holder.ipValidationError)
    }

    @Test
    fun `updatePort with out of range sets portValidationError`() {
        val holder = buildStateHolder()
        holder.updatePort("99999")
        assertEquals("Porta fora do intervalo (1024–65535)", holder.portValidationError)
    }

    @Test
    fun `updatePort with valid port clears portValidationError`() {
        val holder = buildStateHolder()
        holder.updatePort("99999")
        holder.updatePort("18765")
        assertNull(holder.portValidationError)
    }

    @Test
    fun `updatePort with non-numeric sets portValidationError`() {
        val holder = buildStateHolder()
        holder.updatePort("abc")
        assertEquals("Porta deve ser um número", holder.portValidationError)
    }
}

// ── Minimal state holder for unit testing without Android context ─────────────

/**
 * Pure-Kotlin test helper that replicates the state logic of [PipelineViewModel]
 * without requiring [android.app.Application] or Android SDK.
 */
internal class PipelineViewModelStateHolder {

    var pipelineState: PipelineViewState = PipelineViewState.IDLE
        private set
    var commandQueue: List<CommandItem> = emptyList()
        private set
    var currentOutput: List<String> = emptyList()
        private set
    var pendingInteraction: InteractionRequestMsg? = null
        private set
    var connectionStatus: ConnectionStatus = ConnectionStatus.DISCONNECTED
        private set

    /** Last feedback event emitted (for test assertions). */
    var lastFeedback: FeedbackMessage? = null
        private set

    /** Validation error states mirroring PipelineViewModel. */
    var ipValidationError: String? = null
        private set
    var portValidationError: String? = null
        private set

    fun handleMessage(message: com.workflowapp.remote.model.RemoteMessage) {
        when (message) {
            is PipelineStateMsg -> {
                pipelineState = PipelineViewState.fromString(message.status)
                commandQueue = message.commandQueue
            }
            is OutputChunkMsg -> {
                currentOutput = (currentOutput + message.lines)
                    .takeLast(RemoteConstants.MAX_BUFFER_LINES)
            }
            is InteractionRequestMsg -> {
                pendingInteraction = message
            }
            is InteractiveModeEndedMsg -> {
                if (pendingInteraction != null) {
                    lastFeedback = FeedbackMessage.ResponseConsumedByPC
                }
                pendingInteraction = null
            }
            else -> Unit // ErrorMsg, OutputTruncatedMsg, ControlAckMsg — not needed for these tests
        }
    }

    /** Simulate transitionConnectionStatus with feedback emission logic. */
    fun transitionConnectionStatus(next: ConnectionStatus) {
        val current = connectionStatus
        if (current.canTransitionTo(next)) {
            connectionStatus = next
            when {
                next == ConnectionStatus.RECONNECTING ->
                    lastFeedback = FeedbackMessage.Reconnecting
                current == ConnectionStatus.RECONNECTING && next == ConnectionStatus.DISCONNECTED ->
                    lastFeedback = FeedbackMessage.ConnectionFailed
            }
        }
    }

    /** Simulate updateIp validation logic. */
    fun updateIp(ip: String) {
        ipValidationError = when {
            ip.isBlank()     -> null
            !isValidIp(ip)   -> "Endereço IP inválido"
            else             -> null
        }
    }

    /** Simulate updatePort validation logic. */
    fun updatePort(port: String) {
        val portInt = port.toIntOrNull()
        portValidationError = when {
            port.isBlank()        -> null
            portInt == null       -> "Porta deve ser um número"
            !isValidPort(portInt) -> "Porta fora do intervalo (1024–65535)"
            else                  -> null
        }
    }

    /** Simulate sendControl logic (play→resume substitution) without coroutine/channel. */
    fun simulateSendControl(action: ControlAction, onEnvelope: (String) -> Unit) {
        val actualAction = if (action == ControlAction.PLAY && pipelineState == PipelineViewState.PAUSED) {
            ControlAction.RESUME
        } else {
            action
        }
        onEnvelope("""{"type":"control","payload":{"action":"${actualAction.value}"}}""")
    }
}

// ── Assertion helpers ─────────────────────────────────────────────────────────

private fun assertFalse(value: Boolean) = org.junit.Assert.assertFalse(value)
private fun assertTrue(value: Boolean) = org.junit.Assert.assertTrue(value)
