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
    fun getPreferredServerId(): String? = null
    fun setPreferredServerId(serverId: String?) {}
    fun getPreferredRegion(): String? = null
    fun setPreferredRegion(region: String?) {}
    fun getAssignedServerId(): String? = null
    fun setAssignedServerId(serverId: String?) {}
    fun getDeviceTier(): String = "free"
    fun setDeviceTier(tier: String) {}
    fun getAdsConsent(): Boolean = false
    fun setAdsConsent(consented: Boolean) {}
    fun hasAnsweredConsent(): Boolean = false
    fun setHasAnsweredConsent(answered: Boolean) {}
    fun getPremiumExpiresAt(): Long = 0L
    fun setPremiumExpiresAt(timestampMs: Long) {}
    fun getAutoConnectOnBoot(): Boolean = false
    fun setAutoConnectOnBoot(enabled: Boolean) {}
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

    override fun getPreferredServerId(): String? =
        prefs.getString(KEY_PREFERRED_SERVER_ID, null)?.trim()?.takeIf { it.isNotEmpty() }

    override fun setPreferredServerId(serverId: String?) {
        prefs.edit {
            val cleaned = serverId?.trim()?.takeIf { it.isNotEmpty() }
            if (cleaned == null) remove(KEY_PREFERRED_SERVER_ID) else putString(KEY_PREFERRED_SERVER_ID, cleaned)
        }
    }

    override fun getPreferredRegion(): String? =
        prefs.getString(KEY_PREFERRED_REGION, null)?.trim()?.takeIf { it.isNotEmpty() }

    override fun setPreferredRegion(region: String?) {
        prefs.edit {
            val cleaned = region?.trim()?.takeIf { it.isNotEmpty() }
            if (cleaned == null) remove(KEY_PREFERRED_REGION) else putString(KEY_PREFERRED_REGION, cleaned)
        }
    }

    override fun getAssignedServerId(): String? =
        prefs.getString(KEY_ASSIGNED_SERVER_ID, null)?.trim()?.takeIf { it.isNotEmpty() }

    override fun setAssignedServerId(serverId: String?) {
        prefs.edit {
            val cleaned = serverId?.trim()?.takeIf { it.isNotEmpty() }
            if (cleaned == null) remove(KEY_ASSIGNED_SERVER_ID) else putString(KEY_ASSIGNED_SERVER_ID, cleaned)
        }
    }

    override fun getDeviceTier(): String =
        prefs.getString(KEY_DEVICE_TIER, "free")?.trim()?.lowercase()?.takeIf { it == "premium" } ?: "free"

    override fun setDeviceTier(tier: String) {
        val normalized = if (tier.trim().equals("premium", ignoreCase = true)) "premium" else "free"
        prefs.edit { putString(KEY_DEVICE_TIER, normalized) }
    }

    override fun getAdsConsent(): Boolean = prefs.getBoolean(KEY_ADS_CONSENT, false)

    override fun setAdsConsent(consented: Boolean) {
        prefs.edit { putBoolean(KEY_ADS_CONSENT, consented) }
    }

    override fun hasAnsweredConsent(): Boolean = prefs.getBoolean(KEY_CONSENT_ANSWERED, false)

    override fun setHasAnsweredConsent(answered: Boolean) {
        prefs.edit { putBoolean(KEY_CONSENT_ANSWERED, answered) }
    }

    override fun getPremiumExpiresAt(): Long = prefs.getLong(KEY_PREMIUM_EXPIRES_AT, 0L)

    override fun setPremiumExpiresAt(timestampMs: Long) {
        prefs.edit { putLong(KEY_PREMIUM_EXPIRES_AT, timestampMs.coerceAtLeast(0L)) }
    }

    override fun getAutoConnectOnBoot(): Boolean = prefs.getBoolean(KEY_AUTO_CONNECT_ON_BOOT, false)

    override fun setAutoConnectOnBoot(enabled: Boolean) {
        prefs.edit { putBoolean(KEY_AUTO_CONNECT_ON_BOOT, enabled) }
    }

    private companion object {
        const val NAME = "tunnelpilot_settings"
        const val KEY_ROUTING_MODE = "routing_mode"
        const val KEY_SELECTED_APPS = "selected_apps"
        const val KEY_CONTROL_PLANE_URL = "control_plane_url"
        const val KEY_PREFERRED_SERVER_ID = "preferred_server_id"
        const val KEY_PREFERRED_REGION = "preferred_region"
        const val KEY_ASSIGNED_SERVER_ID = "assigned_server_id"
        const val KEY_DEVICE_TIER = "device_tier"
        const val KEY_ADS_CONSENT = "ads_consent"
        const val KEY_CONSENT_ANSWERED = "consent_answered"
        const val KEY_PREMIUM_EXPIRES_AT = "premium_expires_at"
        const val KEY_AUTO_CONNECT_ON_BOOT = "auto_connect_on_boot"
        const val DEFAULT_CONTROL_PLANE_URL = "http://10.0.2.2:8000"
    }
}
