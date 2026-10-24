package com.blawhi3929bd.tunnelpilot.service

import com.blawhi3929bd.tunnelpilot.TunnelPilotController
import com.blawhi3929bd.tunnelpilot.TunnelBackend
import com.blawhi3929bd.tunnelpilot.VpnState
import com.blawhi3929bd.tunnelpilot.data.ConfigStorage
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsProvider
import com.blawhi3929bd.tunnelpilot.data.SettingsStorage
import com.blawhi3929bd.tunnelpilot.provisioning.ControlPlaneApi
import com.blawhi3929bd.tunnelpilot.provisioning.IdentityStorage
import com.blawhi3929bd.tunnelpilot.provisioning.RegisteredServer
import com.blawhi3929bd.tunnelpilot.provisioning.RegistrationResult
import com.blawhi3929bd.tunnelpilot.provisioning.RotationResult
import com.blawhi3929bd.tunnelpilot.provisioning.MigrationResult
import com.wireguard.android.backend.BackendException
import com.wireguard.android.backend.Statistics
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.ByteArrayInputStream

class TunnelPilotServicesIntegrationTest {

    private lateinit var backend: TestBackend
    private lateinit var configStore: TestConfigStorage
    private lateinit var settingsStore: TestSettingsStorage
    private lateinit var identityStore: TestIdentityStorage
    private lateinit var notificationProvider: TestNotificationProvider
    private lateinit var networkMonitor: TestNetworkMonitor
    private lateinit var controlPlane: TestControlPlaneApi

    private val testServer = RegisteredServer(
        id = "srv-1",
        region = "dev",
        hostname = "10.33.209.129",
        publicKey = "X+HVHErh7vmw0KCd4L2zpsWdAZc7VPZziLi42xYR2Bs=",
        port = 51820,
        healthStatus = "ok",
        peerCount = 1,
        peerCapacity = 240,
        capacityRemaining = 239,
    )

    private val validConfig = """
        [Interface]
        PrivateKey = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=
        Address = 10.67.0.2/32
        DNS = 1.1.1.1

        [Peer]
        PublicKey = bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb=
        Endpoint = 10.33.209.129:51820
        AllowedIPs = 0.0.0.0/0
    """.trimIndent()

    @Before
    fun setUp() {
        backend = TestBackend()
        configStore = TestConfigStorage().apply { save(validConfig) }
        settingsStore = TestSettingsStorage()
        identityStore = TestIdentityStorage().apply { saveDeviceToken("token-123") }
        notificationProvider = TestNotificationProvider()
        networkMonitor = TestNetworkMonitor()
        controlPlane = TestControlPlaneApi(testServer)
    }

    private fun createController(
        latencyMs: Long? = 28L,
    ): TunnelPilotController {
        return TunnelPilotController(
            manager = backend,
            configStore = configStore,
            settingsStore = settingsStore,
            identityStore = identityStore,
            installedAppsRepository = object : InstalledAppsProvider {
                override fun getLaunchableApps(): List<InstalledApp> = listOf(
                    InstalledApp("com.example.app", "Example App"),
                )
            },
            controlPlaneClientFactory = { controlPlane },
            vpnPermissionChecker = { null },
            notificationProvider = notificationProvider,
            networkMonitor = networkMonitor,
            latencyMeasurer = { _, _ -> latencyMs },
            startBackgroundTasks = true,
        )
    }

    @Test
    fun autoConnectOnBoot_togglesAndPersists() {
        val controller = createController()
        assertFalse(controller.autoConnectOnBoot.value)

        controller.setAutoConnectOnBoot(true)
        assertTrue(controller.autoConnectOnBoot.value)
        assertTrue(settingsStore.getAutoConnectOnBoot())

        controller.setAutoConnectOnBoot(false)
        assertFalse(controller.autoConnectOnBoot.value)
        assertFalse(settingsStore.getAutoConnectOnBoot())
    }

    @Test
    fun notificationLifecycle_showsConnectingConnectedAndDismissed() = runBlocking {
        val controller = createController()
        settingsStore.setAssignedServerId("srv-1")

        val connectResult = controller.connectNow()
        assertTrue(connectResult.isSuccess)
        assertTrue(notificationProvider.connectingShown)
        assertTrue(notificationProvider.connectedShown)
        assertEquals("srv-1", notificationProvider.lastServerId)
        assertEquals(0L, notificationProvider.lastRxBytes)
        assertEquals(0L, notificationProvider.lastTxBytes)

        val disconnectResult = controller.disconnectNow()
        assertTrue(disconnectResult.isSuccess)
        assertTrue(notificationProvider.dismissed)
    }

    @Test
    fun networkRoaming_triggersReconnectWhenConnected() = runBlocking {
        val controller = createController()
        controller.connectNow()
        assertEquals(1, backend.connectCount)

        // Simulate network change (e.g. WiFi to Cellular)
        networkMonitor.triggerChange()

        // Give the launched reconnect coroutine a moment to execute
        kotlinx.coroutines.delay(200)

        // Backend should have disconnected and connected again
        assertTrue(backend.connectCount >= 2)
        assertTrue(controller.state.value is VpnState.Connected)
    }

    @Test
    fun refreshServers_enrichesWithLatencyMs() = runBlocking {
        val controller = createController(latencyMs = 45L)
        val result = controller.refreshServersNow()
        assertTrue(result.isSuccess)

        val servers = result.getOrThrow()
        assertEquals(1, servers.size)
        assertEquals(45L, servers[0].latencyMs)
        assertEquals(45L, controller.servers.value[0].latencyMs)
    }

    // Test Helpers

    private class TestNotificationProvider : VpnNotificationProvider {
        var connectingShown = false
        var connectedShown = false
        var dismissed = false
        var lastServerId: String? = null
        var lastRxBytes: Long = 0
        var lastTxBytes: Long = 0

        override fun showConnectingNotification() {
            connectingShown = true
        }

        override fun showConnectedNotification(serverId: String?, rxBytes: Long, txBytes: Long) {
            connectedShown = true
            lastServerId = serverId
            lastRxBytes = rxBytes
            lastTxBytes = txBytes
        }

        override fun dismissNotification() {
            dismissed = true
        }
    }

    private class TestNetworkMonitor : NetworkRoamingMonitor {
        private var listener: (() -> Unit)? = null

        override fun start(onNetworkChanged: () -> Unit) {
            listener = onNetworkChanged
        }

        override fun stop() {
            listener = null
        }

        fun triggerChange() {
            listener?.invoke()
        }
    }

    private class TestBackend : TunnelBackend {
        var state = Tunnel.State.DOWN
        var connectCount = 0

        override fun connect(configText: String) {
            connectCount++
            state = Tunnel.State.UP
        }

        override fun disconnect() {
            state = Tunnel.State.DOWN
        }

        override fun currentState(): Tunnel.State = state

        override fun statistics(): Statistics? = null
    }

    private class TestConfigStorage : ConfigStorage {
        private var config: String? = null
        override fun load(): String? = config
        override fun save(config: String) { this.config = config }
        override fun clear() { config = null }
    }

    private class TestSettingsStorage : SettingsStorage {
        private var routingMode = com.blawhi3929bd.tunnelpilot.RoutingMode.ALL_APPS
        private var selectedApps = emptySet<String>()
        private var controlPlaneUrl = "http://10.0.2.2:8000"
        private var preferredServerId: String? = null
        private var preferredRegion: String? = null
        private var assignedServerId: String? = null
        private var deviceTier = "free"
        private var autoConnect = false

        override fun getRoutingMode() = routingMode
        override fun setRoutingMode(mode: com.blawhi3929bd.tunnelpilot.RoutingMode) { routingMode = mode }
        override fun getSelectedApps() = selectedApps
        override fun setSelectedApps(packages: Set<String>) { selectedApps = packages }
        override fun getControlPlaneUrl() = controlPlaneUrl
        override fun setControlPlaneUrl(url: String) { controlPlaneUrl = url }
        override fun getPreferredServerId() = preferredServerId
        override fun setPreferredServerId(serverId: String?) { preferredServerId = serverId }
        override fun getPreferredRegion() = preferredRegion
        override fun setPreferredRegion(region: String?) { preferredRegion = region }
        override fun getAssignedServerId() = assignedServerId
        override fun setAssignedServerId(serverId: String?) { assignedServerId = serverId }
        override fun getDeviceTier() = deviceTier
        override fun setDeviceTier(tier: String) { deviceTier = tier }
        override fun getAutoConnectOnBoot() = autoConnect
        override fun setAutoConnectOnBoot(enabled: Boolean) { autoConnect = enabled }
    }

    private class TestIdentityStorage : IdentityStorage {
        private var token: String? = null
        override fun getOrCreateDeviceId(): String = "test-device-id"
        override fun loadPrivateKey(): String? = null
        override fun savePrivateKey(privateKey: String) {}
        override fun clearPrivateKey() {}
        override fun loadPendingPrivateKey(): String? = null
        override fun savePendingPrivateKey(privateKey: String) {}
        override fun clearPendingPrivateKey() {}
        override fun loadDeviceToken(): String? = token
        override fun saveDeviceToken(token: String) { this.token = token }
        override fun clearDeviceToken() { this.token = null }
        override fun resetIdentity(): String = "new-device-id"
    }

    private class TestControlPlaneApi(private val server: RegisteredServer) : ControlPlaneApi {
        override fun registerDevice(
            deviceId: String,
            publicKey: String,
            appVersion: String,
            deviceToken: String?,
            preferredServerId: String?,
            preferredRegion: String?,
        ): RegistrationResult = RegistrationResult(
            deviceId = deviceId,
            clientAddress = "10.67.0.2/32",
            provisioned = true,
            server = server,
            deviceToken = "new-token",
        )

        override fun rotateDevice(
            deviceId: String,
            publicKey: String,
            appVersion: String,
            deviceToken: String,
        ): RotationResult = RotationResult(
            status = "rotated",
            deviceId = deviceId,
            clientAddress = "10.67.0.2/32",
            provisioned = true,
            server = server,
        )

        override fun migrateDevice(
            deviceId: String,
            targetServerId: String,
            appVersion: String,
            deviceToken: String,
        ): MigrationResult = MigrationResult(
            status = "migrated",
            deviceId = deviceId,
            previousServerId = server.id,
            clientAddress = "10.67.0.2/32",
            provisioned = true,
            server = server,
        )

        override fun revokeDevice(deviceId: String, deviceToken: String): Boolean = true

        override fun listServers(): List<RegisteredServer> = listOf(server)
    }
}
