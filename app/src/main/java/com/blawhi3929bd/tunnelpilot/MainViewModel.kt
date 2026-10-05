package com.blawhi3929bd.tunnelpilot

import android.app.Application
import android.content.Intent
import android.net.VpnService
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.blawhi3929bd.tunnelpilot.data.AppSettingsStore
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsRepository
import com.blawhi3929bd.tunnelpilot.data.SecureConfigStore
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneClient
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.SecureIdentityStore
import com.blawhi3929bd.tunnelpilot.provisioning.WireGuardConfigFactory
import com.wireguard.android.backend.BackendException
import com.wireguard.config.Config
import com.wireguard.crypto.TunnelPilotKeyGenerator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.ByteArrayInputStream

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val appContext = application.applicationContext
    private val manager = WireGuardManager(appContext)
    private val configStore = SecureConfigStore(appContext)
    private val settingsStore = AppSettingsStore(appContext)
    private val identityStore = SecureIdentityStore(appContext)
    private val installedAppsRepository = InstalledAppsRepository(appContext)

    private val _state = MutableStateFlow<VpnState>(VpnState.Disconnected)
    val state: StateFlow<VpnState> = _state.asStateFlow()

    private val _configPresent = MutableStateFlow(configStore.load() != null)
    val configPresent: StateFlow<Boolean> = _configPresent.asStateFlow()

    private val _installedApps = MutableStateFlow<List<InstalledApp>>(emptyList())
    val installedApps: StateFlow<List<InstalledApp>> = _installedApps.asStateFlow()

    private val _selectedApps = MutableStateFlow(settingsStore.getSelectedApps())
    val selectedApps: StateFlow<Set<String>> = _selectedApps.asStateFlow()

    private val _routingMode = MutableStateFlow(settingsStore.getRoutingMode())
    val routingMode: StateFlow<RoutingMode> = _routingMode.asStateFlow()

    private val _reconnectRequired = MutableStateFlow(false)
    val reconnectRequired: StateFlow<Boolean> = _reconnectRequired.asStateFlow()

    private val _controlPlaneUrl = MutableStateFlow(settingsStore.getControlPlaneUrl())
    val controlPlaneUrl: StateFlow<String> = _controlPlaneUrl.asStateFlow()

    private val _provisioningState = MutableStateFlow<ProvisioningState>(ProvisioningState.NotConfigured)
    val provisioningState: StateFlow<ProvisioningState> = _provisioningState.asStateFlow()

    private var statsJob: Job? = null

    init {
        refreshInstalledApps()
    }

    fun requiredVpnPermissionIntent(): Intent? = VpnService.prepare(appContext)

    fun refreshInstalledApps() {
        viewModelScope.launch(Dispatchers.Default) {
            _installedApps.value = installedAppsRepository.getLaunchableApps()
        }
    }

    fun setRoutingMode(mode: RoutingMode) {
        _routingMode.value = mode
        settingsStore.setRoutingMode(mode)
        markRoutingChanged()
    }

    fun toggleApp(packageName: String) {
        _selectedApps.value = buildSet {
            addAll(_selectedApps.value)
            if (!add(packageName)) remove(packageName)
        }
        settingsStore.setSelectedApps(_selectedApps.value)
        markRoutingChanged()
    }

    fun setControlPlaneUrl(url: String) {
        _controlPlaneUrl.value = url
        settingsStore.setControlPlaneUrl(url)
        if (_provisioningState.value is ProvisioningState.Error) {
            _provisioningState.value = ProvisioningState.NotConfigured
        }
    }

    fun provision() {
        if (_state.value.isActive()) {
            _provisioningState.value = ProvisioningState.Error("Disconnect the VPN before provisioning a new configuration")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _provisioningState.value = ProvisioningState.Provisioning
            runCatching {
                val privateKey = identityStore.loadPrivateKey() ?: TunnelPilotKeyGenerator
                    .generatePrivateKey()
                    .also { identityStore.savePrivateKey(it.toBase64()) }
                    .toBase64()
                val privateKeyObject = com.wireguard.crypto.Key.fromBase64(privateKey)
                val publicKey = TunnelPilotKeyGenerator.generatePublicKey(privateKeyObject).toBase64()
                val deviceId = identityStore.getOrCreateDeviceId()

                val baseUrl = _controlPlaneUrl.value.trim()
                require(baseUrl.isNotBlank()) { "Control plane URL is required" }

                val registration = ControlPlaneClient(baseUrl).registerDevice(
                    deviceId = deviceId,
                    publicKey = publicKey,
                    appVersion = BuildConfig.VERSION_NAME,
                )
                val config = WireGuardConfigFactory.create(
                    privateKey = privateKey,
                    clientAddress = registration.clientAddress,
                    server = registration.server,
                )
                Config.parse(ByteArrayInputStream(config.toByteArray(Charsets.UTF_8)))
                configStore.save(config)
                _configPresent.value = true
                _reconnectRequired.value = false
                _provisioningState.value = ProvisioningState.Provisioned(
                    deviceId = registration.deviceId,
                    clientAddress = registration.clientAddress,
                )
            }.onFailure { error ->
                _provisioningState.value = ProvisioningState.Error(
                    error.message ?: "Unable to provision the device",
                )
            }
        }
    }

    fun setConfig(rawConfig: String): Result<Unit> = runCatching {
        require(rawConfig.contains("[Interface]", ignoreCase = true)) {
            "Config must contain an [Interface] section"
        }
        require(rawConfig.contains("[Peer]", ignoreCase = true)) {
            "Config must contain at least one [Peer] section"
        }
        Config.parse(ByteArrayInputStream(rawConfig.toByteArray(Charsets.UTF_8)))
        configStore.save(rawConfig.trim() + "\n")
        _configPresent.value = true
    }

    fun clearConfig() {
        disconnect()
        configStore.clear()
        _configPresent.value = false
        _reconnectRequired.value = false
    }

    fun connect() {
        if (!_configPresent.value) {
            setError("Import a WireGuard configuration first")
            return
        }
        if (_routingMode.value == RoutingMode.SELECTED_APPS && _selectedApps.value.isEmpty()) {
            setError("Select at least one app for Selected apps mode")
            return
        }
        if (requiredVpnPermissionIntent() != null) {
            setError("Android VPN permission is required")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            performConnect()
        }
    }

    fun disconnect() {
        statsJob?.cancel()
        statsJob = null
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { manager.disconnect() }
                .onSuccess { _state.value = VpnState.Disconnected }
                .onFailure { setError(it.message ?: "Unable to disconnect") }
        }
    }

    fun applyRoutingChanges() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { manager.disconnect() }
            performConnect()
        }
    }

    private suspend fun performConnect() {
        val rawConfig = configStore.load()
        if (rawConfig == null) {
            setError("The saved configuration could not be decrypted")
            return
        }

        _state.value = VpnState.Connecting
        try {
            val installed = _installedApps.value.asSequence().map { it.packageName }.toSet()
            val selected = _selectedApps.value.intersect(installed)
            val config = if (_routingMode.value == RoutingMode.SELECTED_APPS) {
                ConfigEditor.withIncludedApplications(rawConfig, selected)
            } else {
                ConfigEditor.withIncludedApplications(rawConfig, emptySet())
            }
            manager.connect(config)
            _reconnectRequired.value = false
            updateStats()
            startStatsPolling()
        } catch (e: BackendException) {
            setError(e.message ?: "WireGuard backend error")
        } catch (e: Exception) {
            setError(e.message ?: "Unable to connect")
        }
    }

    private fun startStatsPolling() {
        statsJob?.cancel()
        statsJob = viewModelScope.launch(Dispatchers.IO) {
            while (_state.value is VpnState.Connected) {
                delay(1000)
                updateStats()
            }
        }
    }

    private fun updateStats() {
        val stats = manager.statistics() ?: return
        _state.value = VpnState.Connected(
            rxBytes = stats.totalRx(),
            txBytes = stats.totalTx(),
        )
    }

    private fun markRoutingChanged() {
        if (_state.value is VpnState.Connected) _reconnectRequired.value = true
    }

    private fun setError(message: String) {
        statsJob?.cancel()
        statsJob = null
        _state.value = VpnState.Error(message)
    }
}
