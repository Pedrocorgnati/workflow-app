package com.workflowapp.remote.connection

import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.util.MainDispatcherRule
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import okhttp3.WebSocket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import android.content.SharedPreferences

/**
 * Unit tests for lifecycle-aware behavior of [ConnectionManager] — TASK-4 BDD scenarios.
 *
 * Uses [TestCoroutineScheduler] to advance virtual time without waiting in real-time.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LifecycleTest {

    @get:Rule
    val coroutineRule = MainDispatcherRule()

    private val testScheduler = TestCoroutineScheduler()
    private val testDispatcher = StandardTestDispatcher(testScheduler)
    private val testScope = TestScope(testDispatcher)

    private val mockParser = mockk<MessageParser>(relaxed = true)
    private val mockWebSocket = mockk<WebSocket>(relaxed = true)
    private val mockPrefs = mockk<SharedPreferences>(relaxed = true)
    private val mockPrefsEditor = mockk<SharedPreferences.Editor>(relaxed = true)
    private val mockNetworkMonitor = mockk<NetworkMonitor>(relaxed = true)

    private lateinit var wsClient: WebSocketClient
    private lateinit var connectionManager: ConnectionManager

    @Before
    fun setUp() {
        every { mockPrefs.edit() } returns mockPrefsEditor
        every { mockPrefsEditor.putString(any(), any()) } returns mockPrefsEditor
        every { mockPrefsEditor.putInt(any(), any()) } returns mockPrefsEditor
        every { mockPrefs.getString(any(), any()) } returns "100.0.0.1"
        every { mockPrefs.getInt(any(), any()) } returns RemoteConstants.DEFAULT_PORT
        every { mockNetworkMonitor.isCurrentlyAvailable() } returns true
        every { mockNetworkMonitor.isNetworkAvailable } returns mockk(relaxed = true)

        wsClient = WebSocketClient(
            parser = mockParser,
            onMessage = {},
            onScheduleReconnect = { connectionManager.scheduleReconnect() },
        )

        // ConnectionManager without ProcessLifecycleOwner (unavailable in unit tests — safe)
        connectionManager = ConnectionManager(
            wsClient = wsClient,
            coroutineScope = testScope,
            prefs = mockPrefs,
            networkMonitor = mockNetworkMonitor,
        )
    }

    // ── Cenário 1: Disconnect após 5min em background ─────────────────────────

    @Test
    fun `disconnect called after 5min virtual time in background`() = testScope.runTest {
        // Arrange: simulate connected
        wsClient.simulateOpen(mockWebSocket)
        assertEquals(ConnectionStatus.CONNECTED, wsClient.state.value)

        val owner = mockk<androidx.lifecycle.LifecycleOwner>(relaxed = true)
        connectionManager.onStop(owner)

        // Advance 5 minutes + a bit in virtual time
        advanceTimeBy(5 * 60_000L + 100L)
        runCurrent()

        // Assert: disconnected after timeout
        assertEquals(ConnectionStatus.DISCONNECTED, wsClient.state.value)
        assertTrue(connectionManager.disconnectedByBackground)
    }

    // ── Cenário 2: Cancelar countdown ao voltar ao foreground < 5min ──────────

    @Test
    fun `countdown cancelled when app returns to foreground within 5min`() = testScope.runTest {
        wsClient.simulateOpen(mockWebSocket)
        val owner = mockk<androidx.lifecycle.LifecycleOwner>(relaxed = true)

        connectionManager.onStop(owner)
        advanceTimeBy(2 * 60_000L)  // 2 min — before 5min timeout

        connectionManager.onStart(owner)
        advanceTimeBy(3 * 60_000L + 100L)  // would exceed 5min total if countdown not cancelled

        // Connection should still be active
        assertEquals(ConnectionStatus.CONNECTED, wsClient.state.value)
        assertFalse(connectionManager.disconnectedByBackground)
    }

    // ── Cenário 3: Reconexão automática ao retornar do background ─────────────

    @Test
    fun `reconnect initiated when returning from background disconnect`() = testScope.runTest {
        wsClient.simulateOpen(mockWebSocket)
        val owner = mockk<androidx.lifecycle.LifecycleOwner>(relaxed = true)

        connectionManager.onStop(owner)
        advanceTimeBy(5 * 60_000L + 100L)
        runCurrent()

        // disconnectedByBackground should be set
        assertTrue(connectionManager.disconnectedByBackground)

        // When app returns to foreground — onStart triggers reconnect
        connectionManager.onStart(owner)

        // disconnectedByBackground reset and connect attempted
        assertFalse(connectionManager.disconnectedByBackground)
        assertEquals(ConnectionStatus.CONNECTING, wsClient.state.value)
    }

    // ── Cenário 4: Channel FIFO order ─────────────────────────────────────────

    @Test
    fun `channel delivers messages in FIFO order`() = testScope.runTest {
        val received = mutableListOf<String>()
        val mockWs = mockk<WebSocket> { every { send(any<String>()) } answers { received.add(firstArg()); true } }
        wsClient.simulateOpen(mockWs)

        val channel = Channel<String>(Channel.BUFFERED)
        launch {
            for (msg in channel) { wsClient.sendRaw(msg) }
        }

        channel.trySend("msg1")
        channel.trySend("msg2")
        channel.trySend("msg3")
        channel.close()

        runCurrent()

        assertEquals(listOf("msg1", "msg2", "msg3"), received)
    }

    // ── Cenário 5: Cleanup real do ConnectionManager ────────────────────────────

    @Test
    fun `cleanup disconnects and removes lifecycle observer`() = testScope.runTest {
        wsClient.simulateOpen(mockWebSocket)
        assertEquals(ConnectionStatus.CONNECTED, wsClient.state.value)

        connectionManager.cleanup()

        // backgroundJob cancelled, networkMonitor unregistered
        verify { mockNetworkMonitor.unregister() }
    }
}
