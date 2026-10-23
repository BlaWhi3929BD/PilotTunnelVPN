package com.blawhi3929bd.tunnelpilot.data

import android.content.Context
import androidx.core.content.edit
import com.blawhi3929bd.tunnelpilot.RoutingMode

interface SettingsStorage {
    fun getRoutingMode(): RoutingMode
    fun setRoutingMode(mode: RoutingMode)
    fun getSelectedApps(): Set<String>
    fun setSelectedApps(packages: Set<String>)
    fun getControlPlaneUrl(): String
    fun setControlPlaneUrl(url: String)
}

class AppSettingsStore(context: Context) : SettingsStorage {
    private val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    override fun getRoutingMode(): RoutingMode = when (prefs.getString(KEY_ROUTING_MODE, null)) {
        RoutingMode.SELECTED_APPS.name -> RoutingMode.SELECTED_APPS
        else -> RoutingMode.ALL_APPS
    }

    override fun setRoutingMode(mode: RoutingMode) {
        prefs.edit { putString(KEY_ROUTING_MODE, mode.name) }
    }

    override fun getSelectedApps(): Set<String> = prefs.getStringSet(KEY_SELECTED_APPS, emptySet()).orEmpty()

    override fun setSelectedApps(packages: Set<String>) {
        prefs.edit { putStringSet(KEY_SELECTED_APPS, packages.toSet()) }
    }

    override fun getControlPlaneUrl(): String =
        prefs.getString(KEY_CONTROL_PLANE_URL, DEFAULT_CONTROL_PLANE_URL).orEmpty()

    override fun setControlPlaneUrl(url: String) {
        prefs.edit { putString(KEY_CONTROL_PLANE_URL, url.trim()) }
    }

    private companion object {
        const val NAME = "tunnelpilot_settings"
        const val KEY_ROUTING_MODE = "routing_mode"
        const val KEY_SELECTED_APPS = "selected_apps"
        const val KEY_CONTROL_PLANE_URL = "control_plane_url"
        const val DEFAULT_CONTROL_PLANE_URL = "http://10.0.2.2:8000"
    }
}
