package com.workflowapp.remote.connection

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/**
 * Unit tests for [NetworkMonitor] — covers TASK-2/ST004 BDD scenarios.
 *
 * Uses Robolectric to provide a real [ConnectivityManager] shadow.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
@OptIn(ExperimentalCoroutinesApi::class)
class NetworkMonitorTest {

    private lateinit var context: Context
    private lateinit var monitor: NetworkMonitor
    private lateinit var connectivityManager: ConnectivityManager

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        connectivityManager =
            context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        monitor = NetworkMonitor(context)
    }

    // ── Cenário 1: Initial state ────────────────────────────────────────────

    @Test
    fun `isNetworkAvailable exposes StateFlow`() {
        // StateFlow should be non-null and have a Boolean value
        assertNotNull(monitor.isNetworkAvailable)
        // Robolectric default: no validated network
        assertFalse(monitor.isNetworkAvailable.value)
    }

    // ── Cenário 2: register is idempotent ───────────────────────────────────

    @Test
    fun `register called twice does not throw`() {
        monitor.register()
        monitor.register() // second call should be no-op
        // No exception means success
    }

    // ── Cenário 3: unregister without register does not throw ───────────────

    @Test
    fun `unregister without register does not throw`() {
        // Never called register()
        monitor.unregister()
        // No exception means success
    }

    // ── Cenário 4: unregister called twice does not throw ───────────────────

    @Test
    fun `unregister called twice does not throw`() {
        monitor.register()
        monitor.unregister()
        monitor.unregister() // second call should be no-op
        // No exception means success
    }

    // ── Cenário 5: isCurrentlyAvailable reflects system state ───────────────

    @Test
    fun `isCurrentlyAvailable returns false without active network`() {
        // Robolectric starts with no validated network by default
        assertFalse(monitor.isCurrentlyAvailable())
    }

    // ── Cenário 6: onAvailable callback updates StateFlow ───────────────────

    @Test
    fun `onAvailable sets isNetworkAvailable to true`() {
        monitor.register()

        val shadowCm = shadowOf(connectivityManager)
        val network = shadowOf(connectivityManager).activeNetwork
            ?: android.net.Network::class.java.getDeclaredConstructor(Int::class.java)
                .apply { isAccessible = true }
                .newInstance(1)

        // Simulate network available via shadow
        shadowCm.networkCallbacks.forEach { callback ->
            callback.onAvailable(network)
        }

        assertTrue(monitor.isNetworkAvailable.value)
    }

    // ── Cenário 7: onLost callback updates StateFlow ────────────────────────

    @Test
    fun `onLost sets isNetworkAvailable to false`() {
        monitor.register()

        val network = android.net.Network::class.java.getDeclaredConstructor(Int::class.java)
            .apply { isAccessible = true }
            .newInstance(1)

        val shadowCm = shadowOf(connectivityManager)

        // First trigger onAvailable
        shadowCm.networkCallbacks.forEach { callback ->
            callback.onAvailable(network)
        }
        assertTrue(monitor.isNetworkAvailable.value)

        // Then trigger onLost
        shadowCm.networkCallbacks.forEach { callback ->
            callback.onLost(network)
        }
        assertFalse(monitor.isNetworkAvailable.value)
    }
}
