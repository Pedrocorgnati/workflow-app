package com.workflowapp.remote.connection

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.workflowapp.remote.util.RemoteLogger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume


/**
 * NetworkMonitor — wraps [ConnectivityManager] to expose network availability as [StateFlow].
 *
 * Must call [register] to start receiving callbacks and [unregister] when done
 * (typically in ViewModel.onCleared or Activity.onDestroy).
 *
 * @param context Application context.
 */
class NetworkMonitor(context: Context) {

    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private val _isNetworkAvailable = MutableStateFlow(false)
    val isNetworkAvailable: StateFlow<Boolean> = _isNetworkAvailable.asStateFlow()

    private var isRegistered = false

    init {
        _isNetworkAvailable.value = isCurrentlyAvailable()
    }

    /** Returns true when the device has an active, validated internet connection. */
    fun isCurrentlyAvailable(): Boolean {
        val network = connectivityManager.activeNetwork ?: return false
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
               capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            _isNetworkAvailable.value = true
            RemoteLogger.d("Network available")
        }

        override fun onLost(network: Network) {
            _isNetworkAvailable.value = false
            RemoteLogger.d("Network lost")
        }

        override fun onCapabilitiesChanged(
            network: Network,
            networkCapabilities: NetworkCapabilities
        ) {
            _isNetworkAvailable.value =
                networkCapabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                networkCapabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        }
    }

    /** Register the network callback. Safe to call multiple times — only registers once. */
    fun register() {
        if (isRegistered) return
        try {
            connectivityManager.registerDefaultNetworkCallback(networkCallback)
            isRegistered = true
            RemoteLogger.d("NetworkCallback registered")
        } catch (e: Exception) {
            RemoteLogger.e("Failed to register NetworkCallback: ${e.message}")
        }
    }

    /**
     * Unregister the network callback. Safe to call multiple times or without prior [register].
     * Call from ViewModel.onCleared() or Activity.onDestroy().
     */
    fun unregister() {
        if (!isRegistered) return
        try {
            connectivityManager.unregisterNetworkCallback(networkCallback)
        } catch (e: IllegalArgumentException) {
            RemoteLogger.w("unregister() called but callback was not registered: ${e.message}")
        }
        isRegistered = false
        RemoteLogger.d("NetworkCallback unregistered")
    }

    /**
     * Suspends until network becomes available.
     * Returns immediately if network is already available.
     * Cancels the one-shot callback if the coroutine is cancelled.
     */
    suspend fun awaitNetworkAvailable(): Unit = suspendCancellableCoroutine { cont ->
        if (isCurrentlyAvailable()) {
            cont.resume(Unit)
            return@suspendCancellableCoroutine
        }
        val oneTimeCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                connectivityManager.unregisterNetworkCallback(this)
                if (cont.isActive) cont.resume(Unit)
            }
        }
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        connectivityManager.registerNetworkCallback(request, oneTimeCallback)
        cont.invokeOnCancellation {
            try { connectivityManager.unregisterNetworkCallback(oneTimeCallback) } catch (_: Exception) {}
        }
    }
}
