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
    val provisioningState: StateFlow<ProvisioningState> = controller.provisioningState
    val servers: StateFlow<List<RegisteredServer>> = controller.servers
    val serversLoaded: StateFlow<Boolean> = controller.serversLoaded
    val serversError: StateFlow<String?> = controller.serversError

    fun requiredVpnPermissionIntent(): Intent? = controller.requiredVpnPermissionIntent()

    fun refreshInstalledApps() = controller.refreshInstalledApps()

    fun setRoutingMode(mode: RoutingMode) = controller.setRoutingMode(mode)

    fun toggleApp(packageName: String) = controller.toggleApp(packageName)

    fun setControlPlaneUrl(url: String) = controller.setControlPlaneUrl(url)

    fun provision() = controller.provision()

    fun rotateDeviceKey() = controller.rotateDeviceKey()

    fun refreshServers() = controller.refreshServers()

    fun resetIdentity() = controller.resetIdentity()

    fun setConfig(rawConfig: String): Result<Unit> = controller.setConfig(rawConfig)

    fun clearConfig() = controller.clearConfig()

    fun connect() = controller.connect()

    fun disconnect() = controller.disconnect()

    fun applyRoutingChanges() = controller.applyRoutingChanges()
}
