package com.blawhi3929bd.tunnelpilot

import android.content.Context
import android.content.Intent
import android.net.VpnService
import com.blawhi3929bd.tunnelpilot.data.AppSettingsStore
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsRepository
import com.blawhi3929bd.tunnelpilot.data.SecureConfigStore
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneClient
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneHttpException
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.RegisteredServer
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
    private val catalogMutex = Mutex()

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

    private val _servers = MutableStateFlow<List<RegisteredServer>>(emptyList())
    val servers: StateFlow<List<RegisteredServer>> = _servers.asStateFlow()

    private val _serversLoaded = MutableStateFlow(false)
    val serversLoaded: StateFlow<Boolean> = _serversLoaded.asStateFlow()

    private val _serversError = MutableStateFlow<String?>(null)
    val serversError: StateFlow<String?> = _serversError.asStateFlow()

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
        if (_routingMode.value == mode) return
        _routingMode.value = mode
        settingsStore.setRoutingMode(mode)
        markRoutingChanged()
    }

    fun toggleApp(packageName: String) {
        val updated = buildSet {
            addAll(_selectedApps.value)
            if (!add(packageName)) remove(packageName)
        }
        _selectedApps.value = updated
        settingsStore.setSelectedApps(updated)
        markRoutingChanged()
    }

    fun setSelectedApps(packages: Set<String>) {
        val cleaned = packages.map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        for (pkg in cleaned) {
            require(PACKAGE_NAME_REGEX.matches(pkg)) {
                "Invalid Android package name: $pkg"
            }
        }
        if (_selectedApps.value == cleaned) return
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
        _serversError.value = null
    }

    fun refreshServers() {
        scope.launch {
            refreshServersNow()
        }
    }

    suspend fun refreshServersNow(): Result<List<RegisteredServer>> = catalogMutex.withLock {
        runCatching {
            val baseUrl = _controlPlaneUrl.value.trim()
            require(baseUrl.isNotBlank()) { "Control plane URL is required" }
            val fetched = ControlPlaneClient(baseUrl).listServers()
            _servers.value = fetched
            _serversLoaded.value = true
            _serversError.value = null
            fetched
        }.onFailure { error ->
            _serversError.value = error.message ?: "Unable to fetch server list"
        }
    }

    fun provision() {
        scope.launch {
            provisionNow()
        }
    }

    suspend fun provisionNow(): Result<ProvisioningState.Provisioned> = operationMutex.withLock {
        syncBackendState()
        if (_state.value.isActive()) {
            val msg = "Disconnect the VPN before provisioning a new configuration"
            _provisioningState.value = ProvisioningState.Error(msg)
            return@withLock Result.failure(IllegalStateException(msg))
        }

        _provisioningState.value = ProvisioningState.Provisioning
        runCatching {
            var activePrivateKey = identityStore.loadPrivateKey()
                ?: identityStore.loadPendingPrivateKey()?.also { identityStore.savePrivateKey(it) }
                ?: run {
                    val generated = TunnelPilotKeyGenerator.generatePrivateKey().toBase64()
                    identityStore.savePrivateKey(generated)
                    generated
                }
            val deviceId = identityStore.getOrCreateDeviceId()
            val existingToken = identityStore.loadDeviceToken()

            val baseUrl = _controlPlaneUrl.value.trim()
            require(baseUrl.isNotBlank()) { "Control plane URL is required" }
            val client = ControlPlaneClient(baseUrl)

            val publicKey = TunnelPilotKeyGenerator.generatePublicKey(
                com.wireguard.crypto.Key.fromBase64(activePrivateKey),
            ).toBase64()

            val registration = try {
                client.registerDevice(
                    deviceId = deviceId,
                    publicKey = publicKey,
                    appVersion = BuildConfig.VERSION_NAME,
                    deviceToken = existingToken,
                )
            } catch (conflict: ControlPlaneHttpException) {
                if (conflict.statusCode == 409 && existingToken != null) {
                    // Authenticated recovery when local key changed or previous rotation timed out:
                    // rotate the server key to match our authenticated local key.
                    val pendingKey = identityStore.loadPendingPrivateKey()
                    if (pendingKey != null && pendingKey != activePrivateKey) {
                        activePrivateKey = pendingKey
                    }
                    val targetPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
                        com.wireguard.crypto.Key.fromBase64(activePrivateKey),
                    ).toBase64()
                    val rotated = client.rotateDevice(
                        deviceId = deviceId,
                        publicKey = targetPublicKey,
                        appVersion = BuildConfig.VERSION_NAME,
                        deviceToken = existingToken,
                    )
                    identityStore.savePrivateKey(activePrivateKey)
                    identityStore.clearPendingPrivateKey()
                    com.blawhi3929bd.tunnelpilot.provisioning.RegistrationResult(
                        deviceId = rotated.deviceId,
                        clientAddress = rotated.clientAddress,
                        provisioned = rotated.provisioned,
                        server = rotated.server,
                        deviceToken = null,
                    )
                } else {
                    throw conflict
                }
            }
            registration.deviceToken?.let(identityStore::saveDeviceToken)
            identityStore.clearPendingPrivateKey()

            val config = WireGuardConfigFactory.create(
                privateKey = activePrivateKey,
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
        syncBackendState()
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
            val oldPublicKey = oldPrivateKey?.let {
                TunnelPilotKeyGenerator.generatePublicKey(
                    com.wireguard.crypto.Key.fromBase64(it),
                ).toBase64()
            }
            // Reuse pendingPrivateKey if a previous rotation attempt timed out before receiving a response.
            val newPrivateKey = identityStore.loadPendingPrivateKey() ?: run {
                val generated = TunnelPilotKeyGenerator.generatePrivateKey().toBase64()
                identityStore.savePendingPrivateKey(generated)
                generated
            }
            val newPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
                com.wireguard.crypto.Key.fromBase64(newPrivateKey),
            ).toBase64()
            val baseUrl = _controlPlaneUrl.value.trim()
            require(baseUrl.isNotBlank()) { "Control plane URL is required" }

            val rotation = try {
                ControlPlaneClient(baseUrl).rotateDevice(
                    deviceId = deviceId,
                    publicKey = newPublicKey,
                    appVersion = BuildConfig.VERSION_NAME,
                    deviceToken = deviceToken,
                )
            } catch (httpError: ControlPlaneHttpException) {
                // Server explicitly rejected this rotation; discard pending key so next attempt generates a fresh one.
                identityStore.clearPendingPrivateKey()
                throw httpError
            }

            try {
                val config = WireGuardConfigFactory.create(
                    privateKey = newPrivateKey,
                    clientAddress = rotation.clientAddress,
                    server = rotation.server,
                )
                Config.parse(ByteArrayInputStream(config.toByteArray(Charsets.UTF_8)))
                identityStore.savePrivateKey(newPrivateKey)
                identityStore.clearPendingPrivateKey()
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
                if (oldPublicKey != null) {
                    runCatching {
                        ControlPlaneClient(baseUrl).rotateDevice(
                            deviceId = deviceId,
                            publicKey = oldPublicKey,
                            appVersion = BuildConfig.VERSION_NAME,
                            deviceToken = deviceToken,
                        )
                    }.onSuccess {
                        identityStore.clearPendingPrivateKey()
                    }
                    runCatching { identityStore.savePrivateKey(oldPrivateKey) }
                }
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
            clearConfigNow(forceLocal = false)
        }
    }

    suspend fun clearConfigNow(forceLocal: Boolean = false): Result<Unit> = operationMutex.withLock {
        syncBackendState()
        if (_state.value.isActive()) {
            val disconnected = disconnectAndWait()
            if (disconnected.isFailure && !forceLocal) {
                return@withLock disconnected
            }
        }
        runCatching {
            val deviceId = identityStore.getOrCreateDeviceId()
            val token = identityStore.loadDeviceToken()
            val baseUrl = _controlPlaneUrl.value.trim()
            if (token != null) {
                if (!forceLocal) {
                    require(baseUrl.isNotBlank()) {
                        "Control plane URL is required to revoke the device on the server"
                    }
                    ControlPlaneClient(baseUrl).revokeDevice(deviceId, token)
                } else if (baseUrl.isNotBlank()) {
                    runCatching { ControlPlaneClient(baseUrl).revokeDevice(deviceId, token) }
                }
            }
            configStore.clear()
            identityStore.clearDeviceToken()
            identityStore.clearPrivateKey()
            _configPresent.value = false
            _reconnectRequired.value = false
            _provisioningState.value = ProvisioningState.NotConfigured
        }.onFailure { error ->
            _provisioningState.value = ProvisioningState.Error(
                "Revocation failed; local credentials preserved: ${error.message ?: "Unknown error"}",
            )
        }
    }

    fun resetIdentity() {
        scope.launch {
            resetIdentityNow(forceLocal = false)
        }
    }

    suspend fun resetIdentityNow(forceLocal: Boolean = false): Result<String> = operationMutex.withLock {
        syncBackendState()
        if (_state.value.isActive()) {
            val disconnected = disconnectAndWait()
            if (disconnected.isFailure && !forceLocal) {
                return@withLock Result.failure(
                    disconnected.exceptionOrNull() ?: IllegalStateException("Unable to disconnect VPN"),
                )
            }
        }
        runCatching {
            val oldDeviceId = identityStore.getOrCreateDeviceId()
            val oldToken = identityStore.loadDeviceToken()
            val baseUrl = _controlPlaneUrl.value.trim()
            if (oldToken != null) {
                if (!forceLocal) {
                    require(baseUrl.isNotBlank()) {
                        "Control plane URL is required to revoke the existing device before resetting identity"
                    }
                    ControlPlaneClient(baseUrl).revokeDevice(oldDeviceId, oldToken)
                } else if (baseUrl.isNotBlank()) {
                    runCatching { ControlPlaneClient(baseUrl).revokeDevice(oldDeviceId, oldToken) }
                }
            }
            configStore.clear()
            val newDeviceId = identityStore.resetIdentity()
            _configPresent.value = false
            _reconnectRequired.value = false
            _provisioningState.value = ProvisioningState.NotConfigured
            newDeviceId
        }.onFailure { error ->
            _provisioningState.value = ProvisioningState.Error(
                "Identity reset aborted because server revocation failed; local token preserved: ${error.message ?: "Unknown error"}",
            )
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
        syncBackendState()
        if (!_state.value.isActive()) {
            return@withLock Result.success(Unit)
        }
        val disconnected = disconnectAndWait()
        if (disconnected.isFailure) return@withLock disconnected
        performConnect()
    }

    fun statusSnapshot(): ControllerStatusSnapshot {
        syncBackendState()
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
            val installedList = installedAppsRepository.getLaunchableApps()
            _installedApps.value = installedList
            val installed = installedList.asSequence().map { it.packageName }.toSet()
            val selected = _selectedApps.value.intersect(installed)
            if (_routingMode.value == RoutingMode.SELECTED_APPS && selected.isEmpty()) {
                val msg = "None of the selected apps are currently installed"
                setError(msg)
                return Result.failure(IllegalStateException(msg))
            }
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
                syncBackendState()
            }
        }
    }

    private fun syncBackendState() {
        if (manager.currentState() == Tunnel.State.UP) {
            updateStats()
        } else if (_state.value is VpnState.Connected) {
            statsJob?.cancel()
            statsJob = null
            _state.value = VpnState.Disconnected
            _reconnectRequired.value = false
        }
    }

    private fun updateStats() {
        if (manager.currentState() != Tunnel.State.UP) return
        val stats = manager.statistics()
        val prev = _state.value as? VpnState.Connected
        _state.value = VpnState.Connected(
            rxBytes = stats?.totalRx() ?: prev?.rxBytes ?: 0L,
            txBytes = stats?.totalTx() ?: prev?.txBytes ?: 0L,
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
        private val PACKAGE_NAME_REGEX = Regex("^[a-zA-Z][a-zA-Z0-9_]*(\\.[a-zA-Z][a-zA-Z0-9_]*)+$")

        @Volatile
        private var instance: TunnelPilotController? = null

        fun getInstance(context: Context): TunnelPilotController =
            instance ?: synchronized(this) {
                instance ?: TunnelPilotController(context.applicationContext).also { instance = it }
            }
    }
}
