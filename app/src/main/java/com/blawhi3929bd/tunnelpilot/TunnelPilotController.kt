package com.blawhi3929bd.tunnelpilot

import android.content.Context
import android.content.Intent
import android.net.VpnService
import com.blawhi3929bd.tunnelpilot.data.AppSettingsStore
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsRepository
import com.blawhi3929bd.tunnelpilot.data.SecureConfigStore
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneClient
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.SecureIdentityStore
import com.blawhi3929bd.tunnelpilot.provisioning.WireGuardConfigFactory
import com.wireguard.android.backend.BackendException
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import com.wireguard.crypto.TunnelPilotKeyGenerator
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.ByteArrayInputStream

data class ControllerStatusSnapshot(
    val vpnState: String,
    val rxBytes: Long,
    val txBytes: Long,
    val errorMessage: String?,
    val configPresent: Boolean,
    val routingMode: String,
    val selectedApps: Set<String>,
    val reconnectRequired: Boolean,
    val controlPlaneUrl: String,
    val provisioningStatus: String,
    val deviceId: String,
    val clientAddress: String?,
    val hasDeviceToken: Boolean,
    val vpnPermissionRequired: Boolean,
)

class TunnelPilotController private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val manager = WireGuardManager(appContext)
    private val configStore = SecureConfigStore(appContext)
    private val settingsStore = AppSettingsStore(appContext)
    private val identityStore = SecureIdentityStore(appContext)
    private val installedAppsRepository = InstalledAppsRepository(appContext)
    private val operationMutex = Mutex()

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

    private val _provisioningState = MutableStateFlow(loadInitialProvisioningState())
    val provisioningState: StateFlow<ProvisioningState> = _provisioningState.asStateFlow()

    private var statsJob: Job? = null

    init {
        refreshInstalledApps()
        scope.launch {
            if (manager.currentState() == Tunnel.State.UP) {
                updateStats()
                startStatsPolling()
            }
        }
    }

    private fun loadInitialProvisioningState(): ProvisioningState {
        val rawConfig = configStore.load() ?: return ProvisioningState.NotConfigured
        if (identityStore.loadDeviceToken() == null) return ProvisioningState.NotConfigured
        val address = rawConfig
            .lineSequence()
            .firstOrNull { it.trim().startsWith("Address", ignoreCase = true) }
            ?.substringAfter("=")
            ?.trim()
            ?: "configured"
        return ProvisioningState.Provisioned(
            deviceId = identityStore.getOrCreateDeviceId(),
            clientAddress = address,
        )
    }

    fun requiredVpnPermissionIntent(): Intent? = VpnService.prepare(appContext)

    fun refreshInstalledApps() {
        scope.launch(Dispatchers.Default) {
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

    fun setSelectedApps(packages: Set<String>) {
        val cleaned = packages.map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        _selectedApps.value = cleaned
        settingsStore.setSelectedApps(cleaned)
        markRoutingChanged()
    }

    fun setControlPlaneUrl(url: String) {
        _controlPlaneUrl.value = url
        settingsStore.setControlPlaneUrl(url)
        if (_provisioningState.value is ProvisioningState.Error) {
            _provisioningState.value = loadInitialProvisioningState()
        }
    }

    fun provision() {
        scope.launch {
            provisionNow()
        }
    }

    suspend fun provisionNow(): Result<ProvisioningState.Provisioned> = operationMutex.withLock {
        if (_state.value.isActive()) {
            val msg = "Disconnect the VPN before provisioning a new configuration"
            _provisioningState.value = ProvisioningState.Error(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }

        _provisioningState.value = ProvisioningState.Provisioning
        runCatching {
            val privateKey = identityStore.loadPrivateKey() ?: run {
                val generated = TunnelPilotKeyGenerator.generatePrivateKey().toBase64()
                identityStore.savePrivateKey(generated)
                generated
            }
            val privateKeyObject = com.wireguard.crypto.Key.fromBase64(privateKey)
            val publicKey = TunnelPilotKeyGenerator.generatePublicKey(privateKeyObject).toBase64()
            val deviceId = identityStore.getOrCreateDeviceId()

            val baseUrl = _controlPlaneUrl.value.trim()
            require(baseUrl.isNotBlank()) { "Control plane URL is required" }

            val registration = ControlPlaneClient(baseUrl).registerDevice(
                deviceId = deviceId,
                publicKey = publicKey,
                appVersion = BuildConfig.VERSION_NAME,
                deviceToken = identityStore.loadDeviceToken(),
            )
            registration.deviceToken?.let(identityStore::saveDeviceToken)

            val config = WireGuardConfigFactory.create(
                privateKey = privateKey,
                clientAddress = registration.clientAddress,
                server = registration.server,
            )
            Config.parse(ByteArrayInputStream(config.toByteArray(Charsets.UTF_8)))
            configStore.save(config)
            _configPresent.value = true
            _reconnectRequired.value = false
            val provisioned = ProvisioningState.Provisioned(
                deviceId = registration.deviceId,
                clientAddress = registration.clientAddress,
            )
            _provisioningState.value = provisioned
            provisioned
        }.onFailure { error ->
            _provisioningState.value = ProvisioningState.Error(
                error.message ?: "Unable to provision the device",
            )
        }
    }

    fun rotateDeviceKey() {
        scope.launch {
            rotateDeviceKeyNow()
        }
    }

    suspend fun rotateDeviceKeyNow(): Result<ProvisioningState.Provisioned> = operationMutex.withLock {
        if (_state.value.isActive()) {
            val msg = "Disconnect the VPN before rotating the client key"
            _provisioningState.value = ProvisioningState.Error(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }

        _provisioningState.value = ProvisioningState.Provisioning
        runCatching {
            val deviceId = identityStore.getOrCreateDeviceId()
            val deviceToken = identityStore.loadDeviceToken()
                ?: error("Device authentication is required before key rotation")
            val oldPrivateKey = identityStore.loadPrivateKey()
                ?: error("The current client private key is missing")
            val oldPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
                com.wireguard.crypto.Key.fromBase64(oldPrivateKey),
            ).toBase64()
            val newPrivateKey = TunnelPilotKeyGenerator.generatePrivateKey().toBase64()
            val newPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
                com.wireguard.crypto.Key.fromBase64(newPrivateKey),
            ).toBase64()
            val baseUrl = _controlPlaneUrl.value.trim()
            require(baseUrl.isNotBlank()) { "Control plane URL is required" }

            val rotation = ControlPlaneClient(baseUrl).rotateDevice(
                deviceId = deviceId,
                publicKey = newPublicKey,
                appVersion = BuildConfig.VERSION_NAME,
                deviceToken = deviceToken,
            )

            try {
                val config = WireGuardConfigFactory.create(
                    privateKey = newPrivateKey,
                    clientAddress = rotation.clientAddress,
                    server = rotation.server,
                )
                Config.parse(ByteArrayInputStream(config.toByteArray(Charsets.UTF_8)))
                identityStore.savePrivateKey(newPrivateKey)
                configStore.save(config)
                _configPresent.value = true
                _reconnectRequired.value = false
                val provisioned = ProvisioningState.Provisioned(
                    deviceId = rotation.deviceId,
                    clientAddress = rotation.clientAddress,
                )
                _provisioningState.value = provisioned
                provisioned
            } catch (localFailure: Exception) {
                runCatching {
                    ControlPlaneClient(baseUrl).rotateDevice(
                        deviceId = deviceId,
                        publicKey = oldPublicKey,
                        appVersion = BuildConfig.VERSION_NAME,
                        deviceToken = deviceToken,
                    )
                }
                runCatching { identityStore.savePrivateKey(oldPrivateKey) }
                throw localFailure
            }
        }.onFailure { error ->
            _provisioningState.value = ProvisioningState.Error(
                error.message ?: "Unable to rotate the device key",
            )
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
        scope.launch {
            clearConfigNow()
        }
    }

    suspend fun clearConfigNow(): Result<Unit> = operationMutex.withLock {
        if (_state.value.isActive()) {
            disconnectAndWait()
        }
        runCatching {
            val deviceId = identityStore.getOrCreateDeviceId()
            val token = identityStore.loadDeviceToken()
            val baseUrl = _controlPlaneUrl.value.trim()
            if (token != null && baseUrl.isNotBlank()) {
                runCatching {
                    ControlPlaneClient(baseUrl).revokeDevice(deviceId, token)
                }
            }
            configStore.clear()
            identityStore.clearDeviceToken()
            identityStore.clearPrivateKey()
            _configPresent.value = false
            _reconnectRequired.value = false
            _provisioningState.value = ProvisioningState.NotConfigured
        }
    }

    fun resetIdentity() {
        scope.launch {
            resetIdentityNow()
        }
    }

    suspend fun resetIdentityNow(): Result<String> = operationMutex.withLock {
        if (_state.value.isActive()) {
            disconnectAndWait()
        }
        runCatching {
            val oldDeviceId = identityStore.getOrCreateDeviceId()
            val oldToken = identityStore.loadDeviceToken()
            val baseUrl = _controlPlaneUrl.value.trim()
            if (oldToken != null && baseUrl.isNotBlank()) {
                runCatching {
                    ControlPlaneClient(baseUrl).revokeDevice(oldDeviceId, oldToken)
                }
            }
            configStore.clear()
            val newDeviceId = identityStore.resetIdentity()
            _configPresent.value = false
            _reconnectRequired.value = false
            _provisioningState.value = ProvisioningState.NotConfigured
            newDeviceId
        }
    }

    fun connect() {
        scope.launch {
            connectNow()
        }
    }

    suspend fun connectNow(): Result<Unit> = operationMutex.withLock {
        if (!_configPresent.value) {
            val msg = "Import a WireGuard configuration first"
            setError(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }
        if (_routingMode.value == RoutingMode.SELECTED_APPS && _selectedApps.value.isEmpty()) {
            val msg = "Select at least one app for Selected apps mode"
            setError(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }
        if (requiredVpnPermissionIntent() != null) {
            val msg = "Android VPN permission is required"
            setError(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }

        performConnect()
    }

    fun disconnect() {
        scope.launch {
            disconnectNow()
        }
    }

    suspend fun disconnectNow(): Result<Unit> = operationMutex.withLock {
        disconnectAndWait()
    }

    fun applyRoutingChanges() {
        scope.launch {
            applyRoutingChangesNow()
        }
    }

    suspend fun applyRoutingChangesNow(): Result<Unit> = operationMutex.withLock {
        if (!_state.value.isActive()) {
            return@withLock Result.success(Unit)
        }
        val disconnected = disconnectAndWait()
        if (disconnected.isFailure) return@withLock disconnected
        performConnect()
    }

    fun statusSnapshot(): ControllerStatusSnapshot {
        updateStats()
        val currentVpn = _state.value
        val currentProv = _provisioningState.value
        val (vpnLabel, rx, tx, vpnErr) = when (currentVpn) {
            VpnState.Disconnected -> Tuple4("Disconnected", 0L, 0L, null)
            VpnState.Connecting -> Tuple4("Connecting", 0L, 0L, null)
            is VpnState.Connected -> Tuple4("Connected", currentVpn.rxBytes, currentVpn.txBytes, null)
            is VpnState.Error -> Tuple4("Error", 0L, 0L, currentVpn.message)
        }
        val (provLabel, clientAddr, provErr) = when (currentProv) {
            ProvisioningState.NotConfigured -> Triple("NotConfigured", null, null)
            ProvisioningState.Provisioning -> Triple("Provisioning", null, null)
            is ProvisioningState.Provisioned -> Triple("Provisioned", currentProv.clientAddress, null)
            is ProvisioningState.Error -> Triple("Error", null, currentProv.message)
        }
        return ControllerStatusSnapshot(
            vpnState = vpnLabel,
            rxBytes = rx,
            txBytes = tx,
            errorMessage = vpnErr ?: provErr,
            configPresent = _configPresent.value,
            routingMode = _routingMode.value.name,
            selectedApps = _selectedApps.value,
            reconnectRequired = _reconnectRequired.value,
            controlPlaneUrl = _controlPlaneUrl.value,
            provisioningStatus = provLabel,
            deviceId = identityStore.getOrCreateDeviceId(),
            clientAddress = clientAddr,
            hasDeviceToken = identityStore.loadDeviceToken() != null,
            vpnPermissionRequired = requiredVpnPermissionIntent() != null,
        )
    }

    private suspend fun disconnectAndWait(): Result<Unit> {
        statsJob?.cancel()
        statsJob = null
        return runCatching {
            manager.disconnect()
            waitForBackendState(Tunnel.State.DOWN)
            _state.value = VpnState.Disconnected
            _reconnectRequired.value = false
        }.onFailure {
            setError(it.message ?: "Unable to disconnect")
        }
    }

    private suspend fun waitForBackendState(target: Tunnel.State, timeoutMs: Long = 2_000) {
        var waitedMs = 0L
        while (manager.currentState() != target && waitedMs < timeoutMs) {
            delay(50)
            waitedMs += 50
        }
        check(manager.currentState() == target) {
            "WireGuard backend did not reach ${target.name} state in time"
        }
    }

    private suspend fun performConnect(): Result<Unit> {
        val rawConfig = configStore.load()
        if (rawConfig == null) {
            val msg = "The saved configuration could not be decrypted"
            setError(msg)
            return Result.failure(IllegalStateException(msg))
        }

        _state.value = VpnState.Connecting
        return try {
            if (_installedApps.value.isEmpty()) {
                _installedApps.value = installedAppsRepository.getLaunchableApps()
            }
            val installed = _installedApps.value.asSequence().map { it.packageName }.toSet()
            val selected = _selectedApps.value.intersect(installed)
            val config = if (_routingMode.value == RoutingMode.SELECTED_APPS) {
                ConfigEditor.withIncludedApplications(rawConfig, selected)
            } else {
                ConfigEditor.withIncludedApplications(rawConfig, emptySet())
            }
            manager.connect(config)
            waitForBackendState(Tunnel.State.UP)
            _reconnectRequired.value = false
            updateStats()
            startStatsPolling()
            Result.success(Unit)
        } catch (e: BackendException) {
            val msg = e.message ?: "WireGuard backend error"
            setError(msg)
            Result.failure(e)
        } catch (e: Exception) {
            val msg = e.message ?: "Unable to connect"
            setError(msg)
            Result.failure(e)
        }
    }

    private fun startStatsPolling() {
        statsJob?.cancel()
        statsJob = scope.launch {
            while (_state.value is VpnState.Connected) {
                delay(1000)
                updateStats()
            }
        }
    }

    private fun updateStats() {
        if (manager.currentState() != Tunnel.State.UP) return
        val stats = manager.statistics()
        _state.value = VpnState.Connected(
            rxBytes = stats?.totalRx() ?: 0L,
            txBytes = stats?.totalTx() ?: 0L,
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

    private data class Tuple4<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)

    companion object {
        @Volatile
        private var instance: TunnelPilotController? = null

        fun getInstance(context: Context): TunnelPilotController =
            instance ?: synchronized(this) {
                instance ?: TunnelPilotController(context.applicationContext).also { instance = it }
            }
    }
}
