package com.workflowapp.remote.util

import timber.log.Timber

/**
 * RemoteLogger — convenience wrapper that forwards all log calls through Timber
 * with the fixed "RemoteConnection" tag.
 *
 * All connection-layer classes (ConnectionManager, MessageParser, BackoffStrategy,
 * NetworkMonitor) use this object so logs are easy to filter in Logcat:
 *   adb logcat -s RemoteConnection
 *
 * Timber is a no-op in release builds unless a Tree is planted — so no log stripping
 * rules are needed in ProGuard.
 */
object RemoteLogger {
    private const val TAG = "RemoteConnection"

    fun d(message: String) = Timber.tag(TAG).d(message)
    fun d(message: String, vararg args: Any?) = Timber.tag(TAG).d(message, *args)

    fun i(message: String) = Timber.tag(TAG).i(message)
    fun i(message: String, vararg args: Any?) = Timber.tag(TAG).i(message, *args)

    fun w(message: String) = Timber.tag(TAG).w(message)
    fun w(message: String, vararg args: Any?) = Timber.tag(TAG).w(message, *args)
    fun w(t: Throwable, message: String) = Timber.tag(TAG).w(t, message)

    fun e(message: String) = Timber.tag(TAG).e(message)
    fun e(message: String, vararg args: Any?) = Timber.tag(TAG).e(message, *args)
    fun e(t: Throwable, message: String) = Timber.tag(TAG).e(t, message)
}
