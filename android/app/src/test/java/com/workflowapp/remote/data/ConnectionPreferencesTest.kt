package com.workflowapp.remote.data

import org.junit.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Unit tests for [ConnectionPreferences] helper functions — module-9 TASK-3.
 *
 * [ConnectionPreferences] itself requires a real Context (EncryptedSharedPreferences
 * depends on Android Keystore), so we test only the pure validation helpers here.
 * Full integration is covered by the existing androidTest suite.
 */
class ConnectionPreferencesTest {

    // ── isValidIp ──────────────────────────────────────────────────────────

    @Test
    fun isValidIp_validIpv4_returnsTrue() {
        assertTrue(isValidIp("192.168.1.100"))
        assertTrue(isValidIp("10.0.0.1"))
        assertTrue(isValidIp("100.64.0.1"))   // Tailscale range
        assertTrue(isValidIp("127.0.0.1"))
    }

    @Test
    fun isValidIp_validIpv6_returnsTrue() {
        assertTrue(isValidIp("::1"))
        assertTrue(isValidIp("2001:db8::1"))
    }

    @Test
    fun isValidIp_blank_returnsFalse() {
        assertFalse(isValidIp(""))
        assertFalse(isValidIp("   "))
    }

    @Test
    fun isValidIp_invalidFormat_returnsFalse() {
        assertFalse(isValidIp("999.999.999.999"))
        assertFalse(isValidIp("not-an-ip"))
        assertFalse(isValidIp("192.168.1"))
        assertFalse(isValidIp("abc.def.ghi.jkl"))
    }

    // ── isValidPort ────────────────────────────────────────────────────────

    @Test
    fun isValidPort_validRange_returnsTrue() {
        assertTrue(isValidPort(1024))
        assertTrue(isValidPort(18765))   // default app port
        assertTrue(isValidPort(65535))
        assertTrue(isValidPort(8080))
    }

    @Test
    fun isValidPort_belowMinimum_returnsFalse() {
        assertFalse(isValidPort(0))
        assertFalse(isValidPort(1))
        assertFalse(isValidPort(1023))
    }

    @Test
    fun isValidPort_aboveMaximum_returnsFalse() {
        assertFalse(isValidPort(65536))
        assertFalse(isValidPort(99999))
        assertFalse(isValidPort(Int.MAX_VALUE))
    }

    @Test
    fun isValidPort_negativeValue_returnsFalse() {
        assertFalse(isValidPort(-1))
        assertFalse(isValidPort(Int.MIN_VALUE))
    }

    // ── Constant correctness ───────────────────────────────────────────────

    @Test
    fun keyConstants_areNonBlank() {
        assertTrue(KEY_LAST_IP.isNotBlank())
        assertTrue(KEY_LAST_PORT.isNotBlank())
    }

    @Test
    fun keyConstants_areDifferent() {
        assertTrue(KEY_LAST_IP != KEY_LAST_PORT)
    }
}
