package com.workflowapp.remote.connection

import com.workflowapp.remote.model.ConnectionStatus
import com.workflowapp.remote.util.MainDispatcherRule
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import okhttp3.WebSocket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.io.IOException

/**
 * Unit tests for [WebSocketClient] — covers the 7 core BDD scenarios from TASK-1.
 *
 * Tests use [simulateOpen]/[simulateFailure]/[simulateClosed] helpers
 * to bypass the OkHttp network layer.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class WebSocketClientTest {

    @get:Rule
    val coroutineRule = MainDispatcherRule()

    private val mockParser = mockk<MessageParser>(relaxed = true)
    private val reconnectCallback = mockk<() -> Unit>(relaxed = true)
    private val mockWebSocket = mockk<WebSocket>(relaxed = true)
    private lateinit var client: WebSocketClient

    @Before
    fun setUp() {
        client = WebSocketClient(
            parser = mockParser,
            onMessage = {},
            onScheduleReconnect = reconnectCallback,
        )
    }

    // ── Cenário 1: Estado inicial ─────────────────────────────────────────────

    @Test
    fun `initial state is DISCONNECTED`() {
        assertEquals(ConnectionStatus.DISCONNECTED, client.state.value)
    }

    // ── Cenário 2: onOpen → CONNECTED ─────────────────────────────────────────

    @Test
    fun `simulateOpen transitions to CONNECTED and isConnected returns true`() {
        client.simulateOpen(mockWebSocket)
        assertEquals(ConnectionStatus.CONNECTED, client.state.value)
        assertTrue(client.isConnected())
    }

    // ── Cenário 3: Close code 1000-1003 — sem reconexão ─────────────────────

    @Test
    fun `simulateClosed with code 1000 transitions to DISCONNECTED without reconnect`() {
        client.simulateOpen(mockWebSocket)
        client.simulateClosed(code = 1000, reason = "Normal")
        assertEquals(ConnectionStatus.DISCONNECTED, client.state.value)
        verify(exactly = 0) { reconnectCallback() }
    }

    @Test
    fun `simulateClosed with code 1003 transitions to DISCONNECTED without reconnect`() {
        client.simulateOpen(mockWebSocket)
        client.simulateClosed(code = 1003, reason = "Unsupported data")
        assertEquals(ConnectionStatus.DISCONNECTED, client.state.value)
        verify(exactly = 0) { reconnectCallback() }
    }

    // ── Cenário 4: Close code 1008 — sem reconexão ───────────────────────────

    @Test
    fun `simulateFailure with code 1008 transitions to DISCONNECTED without reconnect`() {
        client.simulateOpen(mockWebSocket)
        client.simulateFailure(code = 1008, t = IOException("Policy violation"))
        assertEquals(ConnectionStatus.DISCONNECTED, client.state.value)
        verify(exactly = 0) { reconnectCallback() }
    }

    // ── Cenário 5: Falha recuperável → RECONNECTING ──────────────────────────

    @Test
    fun `simulateFailure with recoverable code transitions to RECONNECTING and calls reconnect`() {
        client.simulateOpen(mockWebSocket)
        client.simulateFailure(code = -1, t = IOException("Network error"))
        assertEquals(ConnectionStatus.RECONNECTING, client.state.value)
        verify(exactly = 1) { reconnectCallback() }
    }

    // ── Cenário 6: send() retorna false quando desconectado ──────────────────

    @Test
    fun `sendRaw returns false when not connected`() {
        assertFalse(client.sendRaw("test message"))
    }

    // ── Cenário 7: send() retorna true quando conectado ──────────────────────

    @Test
    fun `sendRaw returns true when connected`() = runTest(UnconfinedTestDispatcher()) {
        every { mockWebSocket.send(any<String>()) } returns true
        client.simulateOpen(mockWebSocket)
        assertTrue(client.sendRaw("test message"))
        verify { mockWebSocket.send("test message") }
    }

    // ── disconnect() é idempotente ────────────────────────────────────────────

    @Test
    fun `disconnect called twice does not throw`() {
        client.simulateOpen(mockWebSocket)
        client.disconnect()
        client.disconnect()  // second call — should be no-op
        assertEquals(ConnectionStatus.DISCONNECTED, client.state.value)
    }
}
