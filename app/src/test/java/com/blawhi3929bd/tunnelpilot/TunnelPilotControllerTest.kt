package com.blawhi3929bd.tunnelpilot

import com.blawhi3929bd.tunnelpilot.data.ConfigStorage
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsProvider
import com.blawhi3929bd.tunnelpilot.data.SettingsStorage
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneApi
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneHttpException
import com.blawhi3929bd.tunnelpilot.provisioning.IdentityStorage
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.RegisteredServer
import com.blawhi3929bd.tunnelpilot.provisioning.RegistrationResult
import com.blawhi3929bd.tunnelpilot.provisioning.RotationResult
import com.blawhi3929bd.tunnelpilot.provisioning.MigrationResult
import com.wireguard.android.backend.Statistics
import com.wireguard.android.backend.Tunnel
import com.wireguard.crypto.TunnelPilotKeyGenerator
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.util.UUID

class TunnelPilotControllerTest {

    private lateinit var backend: FakeTunnelBackend
    private lateinit var configStore: FakeConfigStorage
    private lateinit var settingsStore: FakeSettingsStorage
    private lateinit var identityStore: FakeIdentityStorage
    private lateinit var appsProvider: FakeInstalledAppsProvider
    private lateinit var controlPlane: FakeControlPlaneApi

    private val serverPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
        TunnelPilotKeyGenerator.generatePrivateKey(),
    ).toBase64()
    private val defaultServer by lazy {
        RegisteredServer(
            id = "srv-1",
            region = "dev",
            hostname = "10.33.209.129",
            publicKey = serverPublicKey,
            port = 51820,
            healthStatus = "ok",
            peerCount = 1,
            peerCapacity = 240,
            capacityRemaining = 239,
        )
    }

    @Before
    fun setUp() {
        backend = FakeTunnelBackend()
        configStore = FakeConfigStorage()
        settingsStore = FakeSettingsStorage()
        identityStore = FakeIdentityStorage()
        appsProvider = FakeInstalledAppsProvider(
            listOf(
                InstalledApp(packageName = "com.example.allowed", label = "Allowed App"),
                InstalledApp(packageName = "com.example.second", label = "Second App"),
            ),
        )
        controlPlane = FakeControlPlaneApi(defaultServer)
    }

    private fun createController(): TunnelPilotController = TunnelPilotController(
        manager = backend,
        configStore = configStore,
        settingsStore = settingsStore,
        identityStore = identityStore,
        installedAppsRepository = appsProvider,
        controlPlaneClientFactory = { controlPlane },
        vpnPermissionChecker = { null },
        startBackgroundTasks = false,
    )

    @Test
    fun networkFailures_preserveExistingProvisionedStateAndClientAddress() = runBlocking {
        val controller = createController()

        // 1. Initial provisioning succeeds
        val initial = controller.provisionNow()
        assertTrue(initial.isSuccess)
        val savedConfigBefore = configStore.load()
        assertNotNull(savedConfigBefore)
        assertEquals("Provisioned", controller.statusSnapshot().provisioningStatus)
        assertEquals("10.67.0.2/32", controller.statusSnapshot().clientAddress)
        assertNull(controller.statusSnapshot().errorMessage)

        // 2. Unreachable Control Plane (ConnectException) during re-provision
        controlPlane.registerBehavior = { _, _, _, _ ->
            throw ConnectException("Failed to connect to /127.0.0.1:8000")
        }
        val unreachableResult = controller.provisionNow()
        assertTrue(unreachableResult.isFailure)
        val snapUnreachable = controller.statusSnapshot()
        assertEquals("Provisioned", snapUnreachable.provisioningStatus)
        assertEquals("10.67.0.2/32", snapUnreachable.clientAddress)
        assertTrue(snapUnreachable.configPresent)
        assertTrue(snapUnreachable.hasDeviceToken)
        assertEquals(savedConfigBefore, configStore.load())
        assertTrue(snapUnreachable.errorMessage!!.contains("Failed to connect"))
        val provStateUnreachable = controller.provisioningState.value as ProvisioningState.Provisioned
        assertEquals("10.67.0.2/32", provStateUnreachable.clientAddress)
        assertTrue(provStateUnreachable.lastError!!.contains("Failed to connect"))

        // 3. HTTP 401, 409, and 503 errors preserve Provisioned state and clientAddress
        for (code in listOf(401, 409, 503)) {
            controlPlane.registerBehavior = { _, _, _, _ ->
                throw ControlPlaneHttpException(code, "HTTP $code error from server")
            }
            if (code == 409) {
                controlPlane.rotateBehavior = { _, _, _, _ ->
                    throw ControlPlaneHttpException(409, "HTTP 409 conflict on rotate")
                }
            }
            val httpResult = controller.provisionNow()
            assertTrue(httpResult.isFailure)
            val snapHttp = controller.statusSnapshot()
            assertEquals("Provisioned", snapHttp.provisioningStatus)
            assertEquals("10.67.0.2/32", snapHttp.clientAddress)
            assertEquals(savedConfigBefore, configStore.load())
            assertTrue(snapHttp.errorMessage!!.contains("HTTP $code"))
        }

        // 4. Timeout after sending request preserves Provisioned state and clientAddress
        controlPlane.registerBehavior = { _, _, _, _ ->
            throw SocketTimeoutException("Read timed out")
        }
        val timeoutResult = controller.provisionNow()
        assertTrue(timeoutResult.isFailure)
        val snapTimeout = controller.statusSnapshot()
        assertEquals("Provisioned", snapTimeout.provisioningStatus)
        assertEquals("10.67.0.2/32", snapTimeout.clientAddress)
        assertEquals(savedConfigBefore, configStore.load())
        assertTrue(snapTimeout.errorMessage!!.contains("Read timed out"))

        // 5. Attempting provision while VPN is Connected preserves Provisioned + Connected + clientAddress
        assertTrue(controller.connectNow().isSuccess)
        assertEquals("Connected", controller.statusSnapshot().vpnState)
        val whileConnected = controller.provisionNow()
        assertTrue(whileConnected.isFailure)
        val snapConnected = controller.statusSnapshot()
        assertEquals("Connected", snapConnected.vpnState)
        assertEquals("Provisioned", snapConnected.provisioningStatus)
        assertEquals("10.67.0.2/32", snapConnected.clientAddress)
        assertTrue(snapConnected.errorMessage!!.contains("Disconnect the VPN"))

        // 6. Disconnect and retry when Control Plane recovers -> clears lastError
        assertTrue(controller.disconnectNow().isSuccess)
        controlPlane.resetDefaultBehaviors()
        val recovered = controller.provisionNow()
        assertTrue(recovered.isSuccess)
        val snapRecovered = controller.statusSnapshot()
        assertEquals("Provisioned", snapRecovered.provisioningStatus)
        assertEquals("10.67.0.2/32", snapRecovered.clientAddress)
        assertNull(snapRecovered.errorMessage)
        assertNull((controller.provisioningState.value as ProvisioningState.Provisioned).lastError)
    }

    @Test
    fun unprovisionedDeviceFailure_reportsErrorStateAndNullClientAddress() = runBlocking {
        val controller = createController()
        controlPlane.registerBehavior = { _, _, _, _ ->
            throw ConnectException("Connection refused")
        }

        val res = controller.provisionNow()
        assertTrue(res.isFailure)
        val snap = controller.statusSnapshot()
        assertEquals("Error", snap.provisioningStatus)
        assertNull(snap.clientAddress)
        assertFalse(snap.configPresent)
        assertTrue(snap.errorMessage!!.contains("Connection refused"))
    }

    @Test
    fun selectedAppsMode_enforcesEmptyValidMissingAndReconnectErrorScenarios() = runBlocking {
        val controller = createController()
        assertTrue(controller.provisionNow().isSuccess)

        // 1. Empty selectedApps in SELECTED_APPS mode fails closed on connectNow
        controller.setRoutingMode(RoutingMode.SELECTED_APPS)
        controller.setSelectedApps(emptySet())
        val emptyConnect = controller.connectNow()
        assertTrue(emptyConnect.isFailure)
        assertEquals("Error", controller.statusSnapshot().vpnState)
        assertTrue(controller.statusSnapshot().errorMessage!!.contains("Select at least one app"))
        assertNull(backend.lastConnectedConfig)

        // 2. Valid installed app in SELECTED_APPS mode connects with IncludedApplications
        controller.setSelectedApps(setOf("com.example.allowed"))
        val validConnect = controller.connectNow()
        assertTrue(validConnect.isSuccess)
        assertEquals("Connected", controller.statusSnapshot().vpnState)
        assertTrue(backend.lastConnectedConfig!!.contains("IncludedApplications = com.example.allowed"))

        // 3. Subset of installed + uninstalled apps includes only installed apps on applyRoutingChangesNow
        controller.setSelectedApps(setOf("com.example.allowed", "com.example.uninstalled"))
        assertTrue(controller.statusSnapshot().reconnectRequired)
        val subsetReconnect = controller.applyRoutingChangesNow()
        assertTrue(subsetReconnect.isSuccess)
        assertFalse(controller.statusSnapshot().reconnectRequired)
        assertTrue(backend.lastConnectedConfig!!.contains("IncludedApplications = com.example.allowed"))
        assertFalse(backend.lastConnectedConfig!!.contains("com.example.uninstalled"))

        // 4. Only uninstalled apps selected -> applyRoutingChangesNow fails closed (never falls back to ALL_APPS)
        backend.lastConnectedConfig = null
        controller.setSelectedApps(setOf("com.example.uninstalled"))
        val uninstalledReconnect = controller.applyRoutingChangesNow()
        assertTrue(uninstalledReconnect.isFailure)
        assertEquals("Error", controller.statusSnapshot().vpnState)
        assertTrue(controller.statusSnapshot().errorMessage!!.contains("None of the selected apps are currently installed"))
        assertNull(backend.lastConnectedConfig)

        // 5. Reconnect error when backend.connect throws during applyRoutingChangesNow
        controller.setSelectedApps(setOf("com.example.allowed"))
        assertTrue(controller.connectNow().isSuccess)
        controller.setSelectedApps(setOf("com.example.second"))
        backend.failOnConnect = IllegalStateException("Kernel tunnel creation failed")
        val failedReconnect = controller.applyRoutingChangesNow()
        assertTrue(failedReconnect.isFailure)
        assertEquals("Error", controller.statusSnapshot().vpnState)
        assertTrue(controller.statusSnapshot().errorMessage!!.contains("Kernel tunnel creation failed"))

        // 6. Reconnect error when backend.disconnect fails during applyRoutingChangesNow
        backend.failOnConnect = null
        assertTrue(controller.connectNow().isSuccess)
        controller.setRoutingMode(RoutingMode.ALL_APPS)
        backend.failOnDisconnect = IllegalStateException("Backend failed to bring tunnel down")
        val failedDisconnect = controller.applyRoutingChangesNow()
        assertTrue(failedDisconnect.isFailure)
        assertEquals("Error", controller.statusSnapshot().vpnState)
        assertTrue(controller.statusSnapshot().errorMessage!!.contains("Backend failed to bring tunnel down"))
    }

    @Test
    fun keyRotation_recoversFromPostCommitTimeoutConflictAndLocalFailureWithoutLeakingPrivateKey() = runBlocking {
        val controller = createController()
        assertTrue(controller.provisionNow().isSuccess)

        val initialPrivateKey = identityStore.loadPrivateKey()!!
        val initialConfig = configStore.load()!!

        // 1. Server commits new public key, but response times out before reaching Android
        var serverCommittedOnFirstRotate = false
        controlPlane.rotateBehavior = { deviceId, pubKey, _, _ ->
            controlPlane.serverRegisteredKey = pubKey
            serverCommittedOnFirstRotate = true
            throw SocketTimeoutException("Read timed out after server updated peer")
        }

        val timedOutRotate = controller.rotateDeviceKeyNow()
        assertTrue(timedOutRotate.isFailure)
        assertTrue(serverCommittedOnFirstRotate)
        // Working local config and active privateKey are preserved while pendingPrivateKey holds the new key
        assertEquals(initialPrivateKey, identityStore.loadPrivateKey())
        assertEquals(initialConfig, configStore.load())
        val pendingAfterTimeout = identityStore.loadPendingPrivateKey()
        assertNotNull(pendingAfterTimeout)
        assertNotEquals(initialPrivateKey, pendingAfterTimeout)
        assertEquals("Provisioned", controller.statusSnapshot().provisioningStatus)
        assertEquals("10.67.0.2/32", controller.statusSnapshot().clientAddress)

        // 2. Retry rotateDeviceKeyNow() -> reuses pendingPrivateKey, succeeds idempotently on server
        controlPlane.resetDefaultBehaviors()
        val retryRotate = controller.rotateDeviceKeyNow()
        assertTrue(retryRotate.isSuccess)
        assertEquals(pendingAfterTimeout, identityStore.loadPrivateKey())
        assertNull(identityStore.loadPendingPrivateKey())
        assertTrue(configStore.load()!!.contains(pendingAfterTimeout!!))
        assertNull(controller.statusSnapshot().errorMessage)

        // 3. HTTP 409 key conflict during rotation clears pendingPrivateKey and preserves working config
        val keyBeforeConflict = identityStore.loadPrivateKey()!!
        val configBeforeConflict = configStore.load()!!
        controlPlane.rotateBehavior = { _, _, _, _ ->
            throw ControlPlaneHttpException(409, "client_public_key is already registered to another device_id")
        }
        val conflictRotate = controller.rotateDeviceKeyNow()
        assertTrue(conflictRotate.isFailure)
        assertNull(identityStore.loadPendingPrivateKey())
        assertEquals(keyBeforeConflict, identityStore.loadPrivateKey())
        assertEquals(configBeforeConflict, configStore.load())
        assertEquals("Provisioned", controller.statusSnapshot().provisioningStatus)

        // 4. Local config save failure rolls back server peer to old public key and keeps old private key
        controlPlane.resetDefaultBehaviors()
        val oldPubKey = TunnelPilotKeyGenerator.generatePublicKey(
            com.wireguard.crypto.Key.fromBase64(keyBeforeConflict),
        ).toBase64()
        configStore.failOnSave = IllegalStateException("Keystore write failure")
        val localFailRotate = controller.rotateDeviceKeyNow()
        assertTrue(localFailRotate.isFailure)
        assertEquals(keyBeforeConflict, identityStore.loadPrivateKey())
        assertEquals(oldPubKey, controlPlane.serverRegisteredKey)
        configStore.failOnSave = null

        // 5. Verify no private key was ever sent to Control Plane
        assertFalse(controlPlane.observedPublicKeys.contains(initialPrivateKey))
        assertFalse(controlPlane.observedPublicKeys.contains(pendingAfterTimeout))
        assertFalse(controlPlane.observedPublicKeys.contains(keyBeforeConflict))
    }

    @Test
    fun serverCatalogRefresh_handlesSuccessEmptyAndStaleErrorStates() = runBlocking {
        val controller = createController()
        assertFalse(controller.serversLoaded.value)
        assertFalse(controller.serversLoading.value)

        // 1. Successful catalog load
        val firstRefresh = controller.refreshServersNow()
        assertTrue(firstRefresh.isSuccess)
        assertTrue(controller.serversLoaded.value)
        assertFalse(controller.serversLoading.value)
        assertNull(controller.serversError.value)
        assertEquals(1, controller.servers.value.size)
        assertEquals("srv-1", controller.servers.value[0].id)

        // 2. Subsequent network error preserves cached server list while reporting serversError
        controlPlane.listServersBehavior = {
            throw ConnectException("Control plane unreachable")
        }
        val failedRefresh = controller.refreshServersNow()
        assertTrue(failedRefresh.isFailure)
        assertFalse(controller.serversLoading.value)
        assertEquals(1, controller.servers.value.size)
        assertTrue(controller.serversError.value!!.contains("Control plane unreachable"))

        // 3. Empty catalog response clears list and clears error
        controlPlane.listServersBehavior = { emptyList() }
        val emptyRefresh = controller.refreshServersNow()
        assertTrue(emptyRefresh.isSuccess)
        assertTrue(controller.serversLoaded.value)
        assertTrue(controller.servers.value.isEmpty())
        assertNull(controller.serversError.value)
    }

    @Test
    fun revokeAndReset_preserveCredentialsOnServerFailureAndSupportExplicitForceLocal() = runBlocking {
        val controller = createController()
        assertTrue(controller.provisionNow().isSuccess)
        assertTrue(controller.hasDeviceToken.value)
        assertTrue(controller.configPresent.value)
        val originalDeviceId = identityStore.getOrCreateDeviceId()

        // 1. Server revoke fails -> clearConfigNow(forceLocal=false) and resetIdentityNow(forceLocal=false) preserve credentials
        controlPlane.revokeBehavior = { _, _ ->
            throw ConnectException("Server offline during revoke")
        }
        val failedClear = controller.clearConfigNow(forceLocal = false)
        assertTrue(failedClear.isFailure)
        assertTrue(controller.configPresent.value)
        assertTrue(controller.hasDeviceToken.value)
        assertEquals("Provisioned", controller.statusSnapshot().provisioningStatus)

        val failedReset = controller.resetIdentityNow(forceLocal = false)
        assertTrue(failedReset.isFailure)
        assertTrue(controller.configPresent.value)
        assertTrue(controller.hasDeviceToken.value)
        assertEquals(originalDeviceId, identityStore.getOrCreateDeviceId())

        // 2. Explicit emergency local reset (forceLocal=true) clears local identity & config even when server is offline
        val forcedReset = controller.resetIdentityNow(forceLocal = true)
        assertTrue(forcedReset.isSuccess)
        assertFalse(controller.configPresent.value)
        assertFalse(controller.hasDeviceToken.value)
        assertNotEquals(originalDeviceId, forcedReset.getOrThrow())
        assertEquals("NotConfigured", controller.statusSnapshot().provisioningStatus)
    }

    @Test
    fun reconnectAndRefreshState_synchronizeWithBackendAndSelection() = runBlocking {
        val controller = createController()
        assertTrue(controller.provisionNow().isSuccess)
        controller.toggleApp("com.example.allowed")
        assertEquals(setOf("com.example.allowed"), controller.selectedApps.value)
        controller.clearSelectedApps()
        assertTrue(controller.selectedApps.value.isEmpty())

        assertTrue(controller.connectNow().isSuccess)
        assertEquals("Connected", controller.statusSnapshot().vpnState)
        assertTrue(controller.reconnectNow().isSuccess)
        assertEquals("Connected", controller.statusSnapshot().vpnState)

        // Simulate external tunnel drop (e.g., OS revoke) and verify refreshState() reconciles state
        backend.disconnect()
        controller.refreshState()
        assertEquals("Disconnected", controller.statusSnapshot().vpnState)
    }

    @Test
    fun migrateServer_pinsServerAndUpdatesConfiguration() = runBlocking {
        val controller = createController()
        assertTrue(controller.provisionNow().isSuccess)
        assertEquals("srv-1", controller.assignedServerId.value)
        assertEquals("srv-1", controller.statusSnapshot().assignedServerId)

        val targetServerPublicKey = TunnelPilotKeyGenerator.generatePublicKey(
            TunnelPilotKeyGenerator.generatePrivateKey(),
        ).toBase64()
        val targetServer = RegisteredServer(
            id = "srv-2",
            region = "eu-west",
            hostname = "127.0.0.1",
            publicKey = targetServerPublicKey,
            port = 51821,
            healthStatus = "ok",
            tier = "free",
        )
        controlPlane.migrateBehavior = { deviceId, targetServerId, appVersion, deviceToken ->
            MigrationResult(
                status = "migrated",
                deviceId = deviceId,
                previousServerId = "srv-1",
                clientAddress = "10.68.0.2/32",
                provisioned = true,
                server = targetServer,
                tier = "free",
            )
        }

        val migrated = controller.migrateServerNow("srv-2")
        assertTrue(migrated.isSuccess)
        assertEquals("srv-2", controller.assignedServerId.value)
        assertEquals("srv-2", controller.statusSnapshot().assignedServerId)
        assertEquals("10.68.0.2/32", controller.statusSnapshot().clientAddress)
        assertTrue(configStore.load()!!.contains("10.68.0.2/32"))
        assertTrue(configStore.load()!!.contains(targetServerPublicKey))
    }

    @Test
    fun adsConsent_updatesStateAndPersists() = runBlocking {
        val controller = createController()
        assertFalse(controller.adsConsent.value)
        assertFalse(controller.adsConsentAnswered.value)

        controller.setAdsConsent(true)
        assertTrue(controller.adsConsent.value)
        assertTrue(controller.adsConsentAnswered.value)
        assertTrue(controller.statusSnapshot().adsConsent)
        assertTrue(controller.statusSnapshot().adsConsentAnswered)
    }

    @Test
    fun rewardPremium_grantsTierAndEnforcesExpiry() = runBlocking {
        val controller = createController()
        assertEquals("free", controller.deviceTier.value)

        controller.rewardPremiumAccess(durationHours = 24)
        assertEquals("premium", controller.deviceTier.value)
        assertTrue(controller.premiumExpiresAt.value > System.currentTimeMillis())
        assertEquals("premium", controller.statusSnapshot().deviceTier)

        // Simulate expired timestamp
        settingsStore.setPremiumExpiresAt(System.currentTimeMillis() - 1000L)
        assertTrue(controller.checkPremiumExpiry())
        assertEquals("free", controller.deviceTier.value)
        assertEquals("free", controller.statusSnapshot().deviceTier)
    }

    @Test
    fun refreshState_and_init_automaticallyEnforcePremiumExpiry() = runBlocking {
        val controller = createController()
        controller.rewardPremiumAccess(durationHours = 24)
        assertEquals("premium", controller.deviceTier.value)

        // Set expired timestamp in store and trigger refreshState without explicit checkPremiumExpiry call
        settingsStore.setPremiumExpiresAt(System.currentTimeMillis() - 5000L)
        controller.refreshState()
        assertEquals("free", controller.deviceTier.value)

        // Re-grant and test that fresh controller init also checks and clears expired premium
        settingsStore.setPremiumExpiresAt(System.currentTimeMillis() - 10000L)
        val newController = createController()
        assertEquals("free", newController.deviceTier.value)
        assertEquals(0L, newController.premiumExpiresAt.value)
    }

    private class FakeTunnelBackend : TunnelBackend {
        private var state: Tunnel.State = Tunnel.State.DOWN
        var lastConnectedConfig: String? = null
        var failOnConnect: Exception? = null
        var failOnDisconnect: Exception? = null

        override fun connect(configText: String) {
            failOnConnect?.let { throw it }
            lastConnectedConfig = configText
            state = Tunnel.State.UP
        }

        override fun disconnect() {
            failOnDisconnect?.let { throw it }
            state = Tunnel.State.DOWN
        }

        override fun currentState(): Tunnel.State = state

        override fun statistics(): Statistics? = null
    }

    private class FakeConfigStorage : ConfigStorage {
        private var saved: String? = null
        var failOnSave: Exception? = null

        override fun save(config: String) {
            failOnSave?.let { throw it }
            saved = config
        }

        override fun load(): String? = saved

        override fun clear() {
            saved = null
        }
    }

    private class FakeSettingsStorage : SettingsStorage {
        private var mode: RoutingMode = RoutingMode.ALL_APPS
        private var apps: Set<String> = emptySet()
        private var url: String = "http://127.0.0.1:8000"
        private var preferredServerId: String? = null
        private var preferredRegion: String? = null
        private var assignedServerId: String? = null
        private var deviceTier: String = "free"
        private var adsConsent: Boolean = false
        private var consentAnswered: Boolean = false
        private var premiumExpiresAt: Long = 0L

        override fun getRoutingMode(): RoutingMode = mode
        override fun setRoutingMode(mode: RoutingMode) {
            this.mode = mode
        }

        override fun getSelectedApps(): Set<String> = apps
        override fun setSelectedApps(packages: Set<String>) {
            this.apps = packages
        }

        override fun getControlPlaneUrl(): String = url
        override fun setControlPlaneUrl(url: String) {
            this.url = url
        }

        override fun getPreferredServerId(): String? = preferredServerId
        override fun setPreferredServerId(serverId: String?) {
            this.preferredServerId = serverId
        }

        override fun getPreferredRegion(): String? = preferredRegion
        override fun setPreferredRegion(region: String?) {
            this.preferredRegion = region
        }

        override fun getAssignedServerId(): String? = assignedServerId
        override fun setAssignedServerId(serverId: String?) {
            this.assignedServerId = serverId
        }

        override fun getDeviceTier(): String = deviceTier
        override fun setDeviceTier(tier: String) {
            this.deviceTier = tier
        }

        override fun getAdsConsent(): Boolean = adsConsent
        override fun setAdsConsent(consented: Boolean) {
            this.adsConsent = consented
        }

        override fun hasAnsweredConsent(): Boolean = consentAnswered
        override fun setHasAnsweredConsent(answered: Boolean) {
            this.consentAnswered = answered
        }

        override fun getPremiumExpiresAt(): Long = premiumExpiresAt
        override fun setPremiumExpiresAt(timestampMs: Long) {
            this.premiumExpiresAt = timestampMs
        }
    }

    private class FakeIdentityStorage : IdentityStorage {
        private var deviceId: String = "device-test-1234"
        private var privateKey: String? = null
        private var pendingPrivateKey: String? = null
        private var deviceToken: String? = null

        override fun getOrCreateDeviceId(): String = deviceId
        override fun loadPrivateKey(): String? = privateKey
        override fun savePrivateKey(privateKey: String) {
            this.privateKey = privateKey
        }

        override fun clearPrivateKey() {
            privateKey = null
            pendingPrivateKey = null
        }

        override fun loadPendingPrivateKey(): String? = pendingPrivateKey
        override fun savePendingPrivateKey(privateKey: String) {
            this.pendingPrivateKey = privateKey
        }

        override fun clearPendingPrivateKey() {
            pendingPrivateKey = null
        }

        override fun loadDeviceToken(): String? = deviceToken
        override fun saveDeviceToken(token: String) {
            this.deviceToken = token
        }

        override fun clearDeviceToken() {
            deviceToken = null
        }

        override fun resetIdentity(): String {
            deviceId = "device-${UUID.randomUUID()}"
            privateKey = null
            pendingPrivateKey = null
            deviceToken = null
            return deviceId
        }
    }

    private class FakeInstalledAppsProvider(
        private val apps: List<InstalledApp>,
    ) : InstalledAppsProvider {
        override fun getLaunchableApps(): List<InstalledApp> = apps
    }

    private class FakeControlPlaneApi(
        private val server: RegisteredServer,
    ) : ControlPlaneApi {
        var serverRegisteredKey: String? = null
        val observedPublicKeys = mutableListOf<String>()

        var registerBehavior: ((String, String, String, String?) -> RegistrationResult)? = null
        var rotateBehavior: ((String, String, String, String) -> RotationResult)? = null
        var migrateBehavior: ((String, String, String, String) -> MigrationResult)? = null
        var revokeBehavior: ((String, String) -> Boolean)? = null
        var listServersBehavior: (() -> List<RegisteredServer>)? = null

        fun resetDefaultBehaviors() {
            registerBehavior = null
            rotateBehavior = null
            migrateBehavior = null
            revokeBehavior = null
            listServersBehavior = null
        }

        override fun registerDevice(
            deviceId: String,
            publicKey: String,
            appVersion: String,
            deviceToken: String?,
            preferredServerId: String?,
            preferredRegion: String?,
        ): RegistrationResult {
            observedPublicKeys.add(publicKey)
            registerBehavior?.let { return it(deviceId, publicKey, appVersion, deviceToken) }
            if (serverRegisteredKey != null && serverRegisteredKey != publicKey) {
                throw ControlPlaneHttpException(409, "device_id is already registered with a different public key")
            }
            serverRegisteredKey = publicKey
            return RegistrationResult(
                deviceId = deviceId,
                clientAddress = "10.67.0.2/32",
                provisioned = true,
                server = server,
                deviceToken = deviceToken ?: "issued-device-token-123",
            )
        }

        override fun rotateDevice(
            deviceId: String,
            publicKey: String,
            appVersion: String,
            deviceToken: String,
        ): RotationResult {
            observedPublicKeys.add(publicKey)
            rotateBehavior?.let { return it(deviceId, publicKey, appVersion, deviceToken) }
            val status = if (serverRegisteredKey == publicKey) "unchanged" else "rotated"
            serverRegisteredKey = publicKey
            return RotationResult(
                status = status,
                deviceId = deviceId,
                clientAddress = "10.67.0.2/32",
                provisioned = true,
                server = server,
            )
        }

        override fun migrateDevice(
            deviceId: String,
            targetServerId: String,
            appVersion: String,
            deviceToken: String,
        ): MigrationResult {
            migrateBehavior?.let { return it(deviceId, targetServerId, appVersion, deviceToken) }
            return MigrationResult(
                status = "migrated",
                deviceId = deviceId,
                previousServerId = server.id,
                clientAddress = "10.67.0.2/32",
                provisioned = true,
                server = server,
            )
        }

        override fun revokeDevice(deviceId: String, deviceToken: String): Boolean {
            revokeBehavior?.let { return it(deviceId, deviceToken) }
            return true
        }

        override fun listServers(): List<RegisteredServer> {
            listServersBehavior?.let { return it() }
            return listOf(server)
        }
    }
}
