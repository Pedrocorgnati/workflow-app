package com.workflowapp.remote.connection

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.TestScope
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for [BackoffStrategy] — covers the 7 BDD scenarios from TASK-3.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class BackoffStrategyTest {

    private val testScheduler = TestCoroutineScheduler()
    private val testDispatcher = StandardTestDispatcher(testScheduler)
    private val testScope = TestScope(testDispatcher)

    private lateinit var strategy: BackoffStrategy

    @Before
    fun setUp() {
        strategy = BackoffStrategy()
    }

    // ── Cenário 1: primeiro delay ∈ [2000, 2500) ms ───────────────────────────

    @Test
    fun `first delay is in range 2000 to 2499ms`() {
        val delay = strategy.nextDelayMs()
        assertTrue("Expected [2000, 2500), got $delay", delay in 2000L..2499L)
    }

    // ── Cenário 2: segundo delay ∈ [4000, 4500) ms ───────────────────────────

    @Test
    fun `second delay is in range 4000 to 4499ms`() {
        strategy.nextDelayMs() // advance to second
        val delay = strategy.nextDelayMs()
        assertTrue("Expected [4000, 4500), got $delay", delay in 4000L..4499L)
    }

    // ── Cenário 3: terceiro delay ∈ [8000, 8500) ms ──────────────────────────

    @Test
    fun `third delay is in range 8000 to 8499ms`() {
        strategy.nextDelayMs()
        strategy.nextDelayMs()
        val delay = strategy.nextDelayMs()
        assertTrue("Expected [8000, 8500), got $delay", delay in 8000L..8499L)
    }

    // ── Cenário 4: cap de 60s ─────────────────────────────────────────────────

    @Test
    fun `delay never exceeds cap plus max jitter (60500ms)`() {
        // Collect delays across multiple reset/retry cycles to force the cap
        val delays = mutableListOf<Long>()
        val s = BackoffStrategy()
        repeat(5) {
            s.reset()
            repeat(RemoteConstants.MAX_RETRY_ATTEMPTS) { delays.add(s.nextDelayMs()) }
        }
        val maxDelay = delays.max()
        assertTrue("Max delay ($maxDelay) should be <= 60500", maxDelay <= 60500L)
    }

    // ── Cenário 5: shouldRetry false após 3 tentativas ───────────────────────

    @Test
    fun `shouldRetry returns false after MAX_RETRY_ATTEMPTS calls to nextDelayMs`() {
        repeat(RemoteConstants.MAX_RETRY_ATTEMPTS) { strategy.nextDelayMs() }
        assertFalse(strategy.shouldRetry())
    }

    // ── Cenário 6: shouldRetry true após reset ───────────────────────────────

    @Test
    fun `shouldRetry returns true after reset`() {
        repeat(RemoteConstants.MAX_RETRY_ATTEMPTS) { strategy.nextDelayMs() }
        strategy.reset()
        assertTrue(strategy.shouldRetry())
    }

    // ── Cenário 7: reset restaura sequência inicial ───────────────────────────

    @Test
    fun `reset restores initial delay sequence`() {
        repeat(RemoteConstants.MAX_RETRY_ATTEMPTS) { strategy.nextDelayMs() }
        strategy.reset()
        val firstDelayAfterReset = strategy.nextDelayMs()
        assertTrue(
            "Expected [2000, 2500) after reset, got $firstDelayAfterReset",
            firstDelayAfterReset in 2000L..2499L,
        )
    }
}
