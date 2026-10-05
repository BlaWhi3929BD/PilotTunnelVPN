package com.blawhi3929bd.tunnelpilot.data

import android.content.Context
import com.blawhi3929bd.tunnelpilot.RoutingMode

class AppSettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun getRoutingMode(): RoutingMode = when (prefs.getString(KEY_ROUTING_MODE, null)) {
        RoutingMode.SELECTED_APPS.name -> RoutingMode.SELECTED_APPS
        else -> RoutingMode.ALL_APPS
    }

    fun setRoutingMode(mode: RoutingMode) {
        prefs.edit().putString(KEY_ROUTING_MODE, mode.name).apply()
    }

    fun getSelectedApps(): Set<String> = prefs.getStringSet(KEY_SELECTED_APPS, emptySet()).orEmpty()

    fun setSelectedApps(packages: Set<String>) {
        prefs.edit().putStringSet(KEY_SELECTED_APPS, packages.toSet()).apply()
    }

    private companion object {
        const val NAME = "tunnelpilot_settings"
        const val KEY_ROUTING_MODE = "routing_mode"
        const val KEY_SELECTED_APPS = "selected_apps"
    }
}
