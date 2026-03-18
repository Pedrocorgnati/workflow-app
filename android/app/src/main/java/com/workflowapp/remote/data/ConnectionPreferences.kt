package com.workflowapp.remote.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import timber.log.Timber
import androidx.security.crypto.MasterKey
import com.workflowapp.remote.connection.RemoteConstants
import java.net.InetAddress

private const val TAG                = "ConnectionPreferences"
private const val PREFS_FILE_NAME    = "connection_prefs_encrypted"
const val KEY_LAST_IP                = "last_ip"
const val KEY_LAST_PORT              = "last_port"

/**
 * Persists the last successful connection settings (IP + port) using
 * [EncryptedSharedPreferences] with automatic fallback to plain [SharedPreferences]
 * in environments where the Keystore is unavailable (e.g. older emulators).
 *
 * Settings are saved ONLY after a successful WebSocket connection is established,
 * so only confirmed-working addresses are persisted.
 */
class ConnectionPreferences(private val context: Context) {

    private val prefs by lazy {
        try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREFS_FILE_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            ).also {
                Timber.tag(TAG).d("Using EncryptedSharedPreferences")
            }
        } catch (e: Exception) {
            Timber.tag(TAG).w("EncryptedSharedPreferences unavailable — falling back to plain prefs: %s", e.message)
            context.getSharedPreferences(PREFS_FILE_NAME, Context.MODE_PRIVATE)
        }
    }

    /** Save a confirmed-working connection address. Call only after CONNECTED. */
    fun save(ip: String, port: Int) {
        prefs.edit()
            .putString(KEY_LAST_IP, ip)
            .putInt(KEY_LAST_PORT, port)
            .apply()
        Timber.tag(TAG).d("Saved connection prefs")
    }

    /** Load the last saved IP, or empty string if none persisted. */
    fun loadIp(): String = prefs.getString(KEY_LAST_IP, "") ?: ""

    /** Load the last saved port, defaulting to [RemoteConstants.DEFAULT_PORT]. */
    fun loadPort(): Int = prefs.getInt(KEY_LAST_PORT, RemoteConstants.DEFAULT_PORT)

    /** Clear all stored preferences. */
    fun clear() {
        prefs.edit().clear().apply()
        Timber.tag(TAG).d("Connection prefs cleared")
    }
}

// ── Validation helpers ─────────────────────────────────────────────────────

/**
 * Returns `true` if [ip] is a syntactically valid IPv4 or IPv6 address.
 * Uses [InetAddress.getByName] which accepts dotted-decimal and bracket-free IPv6.
 * Does NOT perform DNS resolution — local IPs are accepted without network access.
 */
fun isValidIp(ip: String): Boolean {
    if (ip.isBlank()) return false
    return try {
        InetAddress.getByName(ip)
        true
    } catch (_: Exception) {
        false
    }
}

/**
 * Returns `true` if [port] falls within the valid user-space range [1024, 65535].
 */
fun isValidPort(port: Int): Boolean = port in 1024..65535
