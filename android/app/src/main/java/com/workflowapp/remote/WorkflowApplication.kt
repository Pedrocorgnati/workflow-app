package com.workflowapp.remote

import android.app.Application
import timber.log.Timber

/**
 * WorkflowApplication — Application subclass.
 *
 * Plants a Timber [Timber.DebugTree] in debug builds only. Release builds produce
 * no logs unless an explicit production Tree is added here (e.g. Crashlytics).
 *
 * Registered in AndroidManifest.xml via android:name=".WorkflowApplication".
 */
class WorkflowApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }
    }
}
