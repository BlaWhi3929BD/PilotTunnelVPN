package com.blawhi3929bd.tunnelpilot

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.RegisteredServer
import kotlinx.coroutines.flow.StateFlow

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val controller = TunnelPilotController.getInstance(application)

    val state: StateFlow<VpnState> = controller.state
    val configPresent: StateFlow<Boolean> = controller.configPresent
    val installedApps: StateFlow<List<InstalledApp>> = controller.installedApps
    val selectedApps: StateFlow<Set<String>> = controller.selectedApps
    val routingMode: StateFlow<RoutingMode> = controller.routingMode
    val reconnectRequired: StateFlow<Boolean> = controller.reconnectRequired
    val controlPlaneUrl: StateFlow<String> = controller.controlPlaneUrl
    val preferredServerId: StateFlow<String?> = controller.preferredServerId
    val preferredRegion: StateFlow<String?> = controller.preferredRegion
    val assignedServerId: StateFlow<String?> = controller.assignedServerId
    val deviceTier: StateFlow<String> = controller.deviceTier
    val adsConsent: StateFlow<Boolean> = controller.adsConsent
    val adsConsentAnswered: StateFlow<Boolean> = controller.adsConsentAnswered
    val premiumExpiresAt: StateFlow<Long> = controller.premiumExpiresAt
    val provisioningState: StateFlow<ProvisioningState> = controller.provisioningState
    val servers: StateFlow<List<RegisteredServer>> = controller.servers
    val serversLoaded: StateFlow<Boolean> = controller.serversLoaded
    val serversLoading: StateFlow<Boolean> = controller.serversLoading
    val serversError: StateFlow<String?> = controller.serversError
    val vpnPermissionRequired: StateFlow<Boolean> = controller.vpnPermissionRequired
    val hasDeviceToken: StateFlow<Boolean> = controller.hasDeviceToken

    fun requiredVpnPermissionIntent(): Intent? = controller.requiredVpnPermissionIntent()

    fun refreshState() = controller.refreshState()

    fun refreshInstalledApps() = controller.refreshInstalledApps()

    fun setRoutingMode(mode: RoutingMode) = controller.setRoutingMode(mode)

    fun toggleApp(packageName: String) = controller.toggleApp(packageName)

    fun setSelectedApps(packages: Set<String>) = controller.setSelectedApps(packages)

    fun clearSelectedApps() = controller.clearSelectedApps()

    fun setControlPlaneUrl(url: String) = controller.setControlPlaneUrl(url)

    fun setPreferredServerId(serverId: String?) = controller.setPreferredServerId(serverId)

    fun setPreferredRegion(region: String?) = controller.setPreferredRegion(region)

    fun setAdsConsent(consented: Boolean) = controller.setAdsConsent(consented)

    fun provision() = controller.provision()

    fun rotateDeviceKey() = controller.rotateDeviceKey()

    fun migrateServer(targetServerId: String) = controller.migrateServer(targetServerId)

    fun upgradeTier(tier: String, purchaseToken: String? = null) = controller.upgradeTier(tier, purchaseToken)

    fun rewardPremiumAccess(durationHours: Int = 24) = controller.rewardPremiumAccess(durationHours)

    fun refreshServers() = controller.refreshServers()

    fun resetIdentity(forceLocal: Boolean = false) = controller.resetIdentity(forceLocal)

    fun setConfig(rawConfig: String): Result<Unit> = controller.setConfig(rawConfig)

    fun clearConfig(forceLocal: Boolean = false) = controller.clearConfig(forceLocal)

    fun connect() = controller.connect()

    fun disconnect() = controller.disconnect()

    fun reconnect() = controller.reconnect()

    fun applyRoutingChanges() = controller.applyRoutingChanges()
}
