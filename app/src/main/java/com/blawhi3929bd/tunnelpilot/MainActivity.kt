package com.blawhi3929bd.tunnelpilot

import android.net.ConnectivityManager
import android.net.Network
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import com.blawhi3929bd.tunnelpilot.provisioning.RegisteredServer
import com.blawhi3929bd.tunnelpilot.ui.AdContainer
import com.blawhi3929bd.tunnelpilot.ui.ConsentDialog
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<MainViewModel>()
    private var connectivityManager: ConnectivityManager? = null

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            runOnUiThread { viewModel.refreshState() }
        }

        override fun onLost(network: Network) {
            runOnUiThread { viewModel.refreshState() }
        }
    }

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        viewModel.refreshState()
        if (it.resultCode == RESULT_OK) viewModel.connect()
    }

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        viewModel.refreshState()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
            }
        }
        connectivityManager = getSystemService(ConnectivityManager::class.java)
        try {
            if (checkSelfPermission(android.Manifest.permission.ACCESS_NETWORK_STATE) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                connectivityManager?.registerDefaultNetworkCallback(networkCallback)
            }
        } catch (_: Exception) {
            // Ignore if network callback registration is unavailable on restricted ROMs.
        }
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) {
                    TunnelPilotScreen(
                        viewModel = viewModel,
                        requestVpnPermission = {
                            val intent = viewModel.requiredVpnPermissionIntent()
                            if (intent != null) vpnPermissionLauncher.launch(intent) else viewModel.connect()
                        },
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshState()
    }

    override fun onDestroy() {
        try {
            connectivityManager?.unregisterNetworkCallback(networkCallback)
        } catch (_: Exception) {
        }
        super.onDestroy()
    }
}

@Composable
private fun TunnelPilotScreen(
    viewModel: MainViewModel,
    requestVpnPermission: () -> Unit,
) {
    var section by rememberSaveable { mutableStateOf("VPN") }
    val state by viewModel.state.collectAsState()
    val configPresent by viewModel.configPresent.collectAsState()
    val apps by viewModel.installedApps.collectAsState()
    val selectedApps by viewModel.selectedApps.collectAsState()
    val routingMode by viewModel.routingMode.collectAsState()
    val reconnectRequired by viewModel.reconnectRequired.collectAsState()
    val controlPlaneUrl by viewModel.controlPlaneUrl.collectAsState()
    val preferredServerId by viewModel.preferredServerId.collectAsState()
    val preferredRegion by viewModel.preferredRegion.collectAsState()
    val assignedServerId by viewModel.assignedServerId.collectAsState()
    val deviceTier by viewModel.deviceTier.collectAsState()
    val adsConsent by viewModel.adsConsent.collectAsState()
    val adsConsentAnswered by viewModel.adsConsentAnswered.collectAsState()
    val premiumExpiresAt by viewModel.premiumExpiresAt.collectAsState()
    val provisioningState by viewModel.provisioningState.collectAsState()
    val servers by viewModel.servers.collectAsState()
    val serversLoaded by viewModel.serversLoaded.collectAsState()
    val serversLoading by viewModel.serversLoading.collectAsState()
    val serversError by viewModel.serversError.collectAsState()
    val vpnPermissionRequired by viewModel.vpnPermissionRequired.collectAsState()
    val hasDeviceToken by viewModel.hasDeviceToken.collectAsState()
    val autoConnectOnBoot by viewModel.autoConnectOnBoot.collectAsState()

    var showConsentDialog by remember { mutableStateOf(false) }

    if (!adsConsentAnswered || showConsentDialog) {
        ConsentDialog(
            onConsentChoice = {
                viewModel.setAdsConsent(it)
                showConsentDialog = false
            },
            onOpenPrivacyPolicy = {
                section = "Setup"
                showConsentDialog = false
            },
        )
    }

    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Text("TunnelPilot", style = MaterialTheme.typography.headlineMedium)
        Text(
            if (deviceTier == "premium") "Premium Ad-Free WireGuard VPN" else "Free WireGuard VPN",
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(16.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("VPN", "Apps", "Config", "Setup").forEach { item ->
                if (section == item) Button(onClick = { section = item }) { Text(item) }
                else OutlinedButton(onClick = { section = item }) { Text(item) }
            }
        }
        Spacer(Modifier.height(16.dp))

        when (section) {
            "VPN" -> VpnSection(
                state = state,
                configPresent = configPresent,
                provisioningState = provisioningState,
                assignedServerId = assignedServerId,
                deviceTier = deviceTier,
                adsConsent = adsConsent,
                premiumExpiresAt = premiumExpiresAt,
                autoConnectOnBoot = autoConnectOnBoot,
                onToggleAutoConnectOnBoot = viewModel::setAutoConnectOnBoot,
                vpnPermissionRequired = vpnPermissionRequired,
                routingMode = routingMode,
                selectedCount = selectedApps.size,
                reconnectRequired = reconnectRequired,
                onConnect = requestVpnPermission,
                onDisconnect = viewModel::disconnect,
                onReconnect = viewModel::reconnect,
                onApplyRouting = viewModel::applyRoutingChanges,
                onRoutingMode = viewModel::setRoutingMode,
                onAdsConsent = viewModel::setAdsConsent,
                onRewardPremium = { viewModel.rewardPremiumAccess(24) },
                onUpgradeTier = { viewModel.upgradeTier("premium", "play-billing-verified-token") },
                onOpenSetup = { section = "Setup" },
                onOpenConfig = { section = "Config" },
                onOpenApps = { section = "Apps" },
            )
            "Apps" -> AppsSection(
                apps = apps,
                selectedApps = selectedApps,
                routingMode = routingMode,
                onToggle = viewModel::toggleApp,
                onSetSelectedApps = viewModel::setSelectedApps,
                onClearSelection = viewModel::clearSelectedApps,
                onRefresh = viewModel::refreshInstalledApps,
            )
            "Config" -> ConfigSection(
                configPresent = configPresent,
                provisioningState = provisioningState,
                onSave = viewModel::setConfig,
                onClear = { viewModel.clearConfig(forceLocal = false) },
                onForceClearLocal = { viewModel.clearConfig(forceLocal = true) },
            )
            "Setup" -> SetupSection(
                controlPlaneUrl = controlPlaneUrl,
                preferredServerId = preferredServerId,
                preferredRegion = preferredRegion,
                assignedServerId = assignedServerId,
                deviceTier = deviceTier,
                provisioningState = provisioningState,
                hasDeviceToken = hasDeviceToken,
                servers = servers,
                serversLoaded = serversLoaded,
                serversLoading = serversLoading,
                serversError = serversError,
                onControlPlaneUrl = viewModel::setControlPlaneUrl,
                onSelectServer = viewModel::setPreferredServerId,
                onSelectRegion = viewModel::setPreferredRegion,
                onProvision = viewModel::provision,
                onMigrateServer = viewModel::migrateServer,
                onRotateKey = viewModel::rotateDeviceKey,
                onRefreshServers = viewModel::refreshServers,
                onResetIdentity = { viewModel.resetIdentity(forceLocal = false) },
                onForceResetLocalIdentity = { viewModel.resetIdentity(forceLocal = true) },
                onReviewPrivacyChoices = { showConsentDialog = true },
            )
        }
    }
}

@Composable
private fun VpnSection(
    state: VpnState,
    configPresent: Boolean,
    provisioningState: ProvisioningState,
    assignedServerId: String?,
    deviceTier: String,
    adsConsent: Boolean,
    premiumExpiresAt: Long = 0L,
    autoConnectOnBoot: Boolean = false,
    onToggleAutoConnectOnBoot: (Boolean) -> Unit = {},
    vpnPermissionRequired: Boolean,
    routingMode: RoutingMode,
    selectedCount: Int,
    reconnectRequired: Boolean,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
    onReconnect: () -> Unit,
    onApplyRouting: () -> Unit,
    onRoutingMode: (RoutingMode) -> Unit,
    onAdsConsent: (Boolean) -> Unit,
    onRewardPremium: () -> Unit = {},
    onUpgradeTier: () -> Unit,
    onOpenSetup: () -> Unit,
    onOpenConfig: () -> Unit,
    onOpenApps: () -> Unit,
) {
    val pinnedServer = (provisioningState as? ProvisioningState.Provisioned)?.serverId ?: assignedServerId
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        if (!configPresent) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp)) {
                    Text("Welcome to TunnelPilot", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "No WireGuard configuration is installed yet. Use automatic Setup to provision this device " +
                            "with a Control Plane server, or import a configuration manually.",
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = onOpenSetup) { Text("Open Setup") }
                        OutlinedButton(onClick = onOpenConfig) { Text("Import Config") }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
        }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(18.dp)) {
                Text(stateLabel(state), style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(6.dp))
                Text(routingDescription(routingMode, selectedCount))
                Spacer(Modifier.height(8.dp))
                Text(
                    text = provisioningSummary(provisioningState, configPresent),
                    style = MaterialTheme.typography.bodySmall,
                )
                if (!pinnedServer.isNullOrBlank()) {
                    Text(
                        text = "Pinned server: $pinnedServer (Plan: ${deviceTier.uppercase(Locale.US)})",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Text(
                    text = if (vpnPermissionRequired) {
                        "VPN permission: required (Android will prompt on Connect)"
                    } else {
                        "VPN permission: granted"
                    },
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(16.dp))

                Text("Routing mode", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (routingMode == RoutingMode.ALL_APPS) {
                        Button(onClick = {}) { Text("All apps") }
                    } else {
                        OutlinedButton(onClick = { onRoutingMode(RoutingMode.ALL_APPS) }) { Text("All apps") }
                    }
                    if (routingMode == RoutingMode.SELECTED_APPS) {
                        Button(onClick = {}) { Text("Selected apps") }
                    } else {
                        OutlinedButton(onClick = { onRoutingMode(RoutingMode.SELECTED_APPS) }) { Text("Selected apps") }
                    }
                }
                if (routingMode == RoutingMode.SELECTED_APPS && selectedCount == 0) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Selected-apps mode requires at least one app. Choose apps in the Apps tab before connecting.",
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(Modifier.height(4.dp))
                    TextButton(onClick = onOpenApps) { Text("Select apps") }
                }
                Spacer(Modifier.height(12.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Checkbox(
                        checked = autoConnectOnBoot,
                        onCheckedChange = onToggleAutoConnectOnBoot,
                    )
                    Text("Connect on device reboot", style = MaterialTheme.typography.bodyMedium)
                }
                Spacer(Modifier.height(12.dp))

                Button(
                    onClick = onConnect,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = configPresent && !state.isActive(),
                ) {
                    Text(if (vpnPermissionRequired) "Grant permission & Connect" else "Connect")
                }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = onDisconnect,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = state is VpnState.Connected || state is VpnState.Connecting,
                ) { Text("Disconnect") }

                if (state is VpnState.Connected || state is VpnState.Error) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = onReconnect,
                        modifier = Modifier.fillMaxWidth(),
                        enabled = configPresent,
                    ) { Text("Reconnect tunnel") }
                }

                if (reconnectRequired) {
                    Spacer(Modifier.height(8.dp))
                    Button(
                        onClick = onApplyRouting,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Reconnect with new routing")
                    }
                }

                if (state is VpnState.Connected) {
                    Spacer(Modifier.height(12.dp))
                    Text("Received: ${formatBytes(state.rxBytes)}")
                    Text("Sent: ${formatBytes(state.txBytes)}")
                    if (state.rxBytes == 0L && state.txBytes > 0L) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Traffic sent but 0 B received so far. If connectivity stalls, check gateway reachability in Setup.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                if (state is VpnState.Error) {
                    Spacer(Modifier.height(10.dp))
                    Text(state.message, color = MaterialTheme.colorScheme.error)
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        if (deviceTier == "premium") {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("TunnelPilot Premium Active", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(4.dp))
                    val hoursRemaining = if (premiumExpiresAt > 0L) {
                        val diff = premiumExpiresAt - System.currentTimeMillis()
                        val hours = (diff / (3600 * 1000L)).coerceAtLeast(0)
                        val mins = ((diff % (3600 * 1000L)) / (60 * 1000L)).coerceAtLeast(0)
                        " (Reward expires in ${hours}h ${mins}m)"
                    } else ""
                    Text(
                        "Ad-free experience and access to all Premium regional gateways enabled$hoursRemaining.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        } else {
            AdContainer(
                deviceTier = deviceTier,
                adsConsent = adsConsent,
                onWatchRewarded = onRewardPremium,
            )
            Spacer(Modifier.height(8.dp))
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Free Plan Options", style = MaterialTheme.typography.titleSmall)
                    Spacer(Modifier.height(4.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Checkbox(checked = adsConsent, onCheckedChange = onAdsConsent)
                        Text(
                            "Allow personalized in-app sponsor recommendations",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = onRewardPremium, modifier = Modifier.weight(1f)) {
                            Text("✨ Watch Ad (24h)")
                        }
                        OutlinedButton(onClick = onUpgradeTier, modifier = Modifier.weight(1f)) {
                            Text("Upgrade Plan")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppsSection(
    apps: List<com.blawhi3929bd.tunnelpilot.data.InstalledApp>,
    selectedApps: Set<String>,
    routingMode: RoutingMode,
    onToggle: (String) -> Unit,
    onSetSelectedApps: (Set<String>) -> Unit,
    onClearSelection: () -> Unit,
    onRefresh: () -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    val installedPackageNames = remember(apps) { apps.map { it.packageName }.toSet() }
    val installedSelectedCount = remember(selectedApps, installedPackageNames) {
        selectedApps.count { it in installedPackageNames }
    }
    val filtered = apps.filter {
        query.isBlank() || it.label.contains(query, ignoreCase = true) || it.packageName.contains(query, ignoreCase = true)
    }

    Text("Apps allowed to use the VPN", style = MaterialTheme.typography.titleLarge)
    Text("Selected-apps mode keeps the VPN connection active, but Android routes only the selected apps through it.")
    Spacer(Modifier.height(4.dp))
    Text(
        "Selected: $installedSelectedCount installed app(s) (${apps.size} launchable apps detected)",
        style = MaterialTheme.typography.bodySmall,
    )
    if (routingMode == RoutingMode.SELECTED_APPS && installedSelectedCount == 0) {
        Spacer(Modifier.height(4.dp))
        Text(
            "Select at least one installed app to connect in Selected-apps mode.",
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = query,
        onValueChange = { query = it },
        Modifier.fillMaxWidth(),
        label = { Text("Search apps") },
        singleLine = true,
    )
    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
        OutlinedButton(
            onClick = {
                val browsers = apps.filter { isBrowserPackage(it.packageName, it.label) }.map { it.packageName }
                onSetSelectedApps(selectedApps + browsers)
            },
            modifier = Modifier.weight(1f),
        ) { Text("+ Browsers") }
        OutlinedButton(
            onClick = {
                val chat = apps.filter { isMessengerPackage(it.packageName, it.label) }.map { it.packageName }
                onSetSelectedApps(selectedApps + chat)
            },
            modifier = Modifier.weight(1f),
        ) { Text("+ Chat") }
        OutlinedButton(
            onClick = {
                val media = apps.filter { isMediaPackage(it.packageName, it.label) }.map { it.packageName }
                onSetSelectedApps(selectedApps + media)
            },
            modifier = Modifier.weight(1f),
        ) { Text("+ Media") }
    }
    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        OutlinedButton(onClick = onRefresh, Modifier.weight(1f)) { Text("Refresh app list") }
        OutlinedButton(
            onClick = onClearSelection,
            Modifier.weight(1f),
            enabled = selectedApps.isNotEmpty(),
        ) { Text("Clear selection") }
    }
    Spacer(Modifier.height(8.dp))
    if (filtered.isEmpty()) {
        Text(
            if (apps.isEmpty()) "No launchable apps found."
            else "No apps match \"$query\".",
            style = MaterialTheme.typography.bodyMedium,
        )
    } else {
        LazyColumn(Modifier.fillMaxSize()) {
            items(filtered, key = { it.packageName }) { app ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = app.packageName in selectedApps,
                        onCheckedChange = { onToggle(app.packageName) },
                    )
                    Column(Modifier.weight(1f)) {
                        Text(app.label)
                        Text(app.packageName, style = MaterialTheme.typography.bodySmall)
                    }
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun SetupSection(
    controlPlaneUrl: String,
    preferredServerId: String?,
    preferredRegion: String?,
    assignedServerId: String?,
    deviceTier: String,
    provisioningState: ProvisioningState,
    hasDeviceToken: Boolean,
    servers: List<RegisteredServer>,
    serversLoaded: Boolean,
    serversLoading: Boolean,
    serversError: String?,
    onControlPlaneUrl: (String) -> Unit,
    onSelectServer: (String?) -> Unit,
    onSelectRegion: (String?) -> Unit,
    onProvision: () -> Unit,
    onMigrateServer: (String) -> Unit,
    onRotateKey: () -> Unit,
    onRefreshServers: () -> Unit,
    onResetIdentity: () -> Unit,
    onForceResetLocalIdentity: () -> Unit,
    onReviewPrivacyChoices: () -> Unit = {},
) {
    val isBusy = provisioningState is ProvisioningState.Provisioning
    val isProvisioned = provisioningState is ProvisioningState.Provisioned && hasDeviceToken
    val currentServerId = (provisioningState as? ProvisioningState.Provisioned)?.serverId ?: assignedServerId
    val latestError = when (provisioningState) {
        is ProvisioningState.Provisioned -> provisioningState.lastError
        is ProvisioningState.Error -> provisioningState.message
        else -> null
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        Text("Automatic server setup", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(8.dp))
        Text(
            "TunnelPilot generates the WireGuard client key on this device, registers only the public key, " +
                "and builds the encrypted client configuration from the gateway response.",
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = controlPlaneUrl,
            onValueChange = onControlPlaneUrl,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Control plane URL") },
            singleLine = true,
            enabled = !isBusy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        Spacer(Modifier.height(12.dp))
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = onProvision,
            enabled = !isBusy,
        ) {
            Text(if (isBusy) "Provisioning…" else "Provision device")
        }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onRotateKey,
            enabled = !isBusy && isProvisioned,
        ) {
            Text("Rotate client key")
        }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onRefreshServers,
            enabled = !serversLoading,
        ) {
            Text(if (serversLoading) "Checking server status…" else "Check server status")
        }
        Spacer(Modifier.height(8.dp))
        TextButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onResetIdentity,
            enabled = !isBusy,
        ) {
            Text("Reset local device identity")
        }
        if (latestError != null && hasDeviceToken) {
            TextButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = onForceResetLocalIdentity,
                enabled = !isBusy,
            ) {
                Text(
                    "Force local identity reset (offline / skip server revoke)",
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        when (provisioningState) {
            ProvisioningState.NotConfigured -> Text("Not provisioned yet.")
            ProvisioningState.Provisioning -> Text("Provisioning…")
            is ProvisioningState.Provisioned -> {
                Text("Device ID: ${provisioningState.deviceId}")
                Text("VPN address: ${provisioningState.clientAddress}")
                if (!currentServerId.isNullOrBlank()) {
                    Text("Pinned server: $currentServerId (re-provision & key rotation keep this server)")
                }
                Text(
                    if (hasDeviceToken) "Device authentication token: stored in Keystore"
                    else "Configuration mode: manual or legacy (no device token)",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text("The generated configuration is stored encrypted locally.")
                if (provisioningState.lastError != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        provisioningState.lastError,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            is ProvisioningState.Error -> {
                Text(
                    provisioningState.message,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        if (serversLoading) {
            Spacer(Modifier.height(8.dp))
            Text("Loading gateway catalog from control plane…", style = MaterialTheme.typography.bodySmall)
        }
        if (serversError != null) {
            Spacer(Modifier.height(8.dp))
            Text(serversError, color = MaterialTheme.colorScheme.error)
            if (servers.isNotEmpty()) {
                Text(
                    "Showing last known gateway catalog below (cached).",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        if (servers.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text("Gateway catalog & region selection", style = MaterialTheme.typography.titleMedium)
            val regions = remember(servers) { servers.map { it.region }.distinct().sorted() }
            if (regions.size > 1) {
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (preferredRegion == null) {
                        Button(onClick = { onSelectRegion(null) }) { Text("All regions") }
                    } else {
                        OutlinedButton(onClick = { onSelectRegion(null) }) { Text("All regions") }
                    }
                    regions.forEach { reg ->
                        if (preferredRegion.equals(reg, ignoreCase = true)) {
                            Button(onClick = { onSelectRegion(reg) }) { Text(reg) }
                        } else {
                            OutlinedButton(onClick = { onSelectRegion(reg) }) { Text(reg) }
                        }
                    }
                }
            }
            val visibleServers = if (preferredRegion.isNullOrBlank()) {
                servers
            } else {
                servers.filter { it.region.equals(preferredRegion, ignoreCase = true) }
            }
            Spacer(Modifier.height(8.dp))
            visibleServers.forEach { server ->
                val cap = when {
                    server.peerCount != null && server.peerCapacity != null && server.capacityRemaining != null ->
                        " (${server.peerCount}/${server.peerCapacity} peers, ${server.capacityRemaining} free)"
                    server.peerCount != null && server.peerCapacity != null ->
                        " (${server.peerCount}/${server.peerCapacity} peers)"
                    else -> ""
                }
                val isCurrentPinned = isProvisioned && currentServerId == server.id
                val isHealthyAndAvailable = server.healthStatus in setOf("ok", "unconfigured") &&
                    (server.capacityRemaining == null || server.capacityRemaining > 0)
                val tierAllowed = server.tier != "premium" || deviceTier == "premium"

                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        val latencyBadge = if (server.latencyMs != null) " • ${server.latencyMs} ms" else ""
                        Text(
                            "${server.id} [${server.region} / ${server.tier.uppercase(Locale.US)}] — ${server.healthStatus}$cap$latencyBadge",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Text(
                            "${server.hostname}:${server.port}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Spacer(Modifier.height(6.dp))
                        if (isProvisioned) {
                            if (isCurrentPinned) {
                                Text("Pinned to this server", style = MaterialTheme.typography.bodySmall)
                            } else {
                                OutlinedButton(
                                    onClick = { onMigrateServer(server.id) },
                                    enabled = !isBusy && isHealthyAndAvailable && tierAllowed,
                                ) {
                                    Text(
                                        when {
                                            !tierAllowed -> "Requires Premium"
                                            !isHealthyAndAvailable -> "Server unavailable (${server.healthStatus})"
                                            else -> "Migrate to ${server.id}"
                                        },
                                    )
                                }
                            }
                        } else {
                            if (preferredServerId == server.id) {
                                OutlinedButton(onClick = { onSelectServer(null) }, enabled = !isBusy) {
                                    Text("Selected for provisioning (tap for Auto)")
                                }
                            } else {
                                OutlinedButton(
                                    onClick = { onSelectServer(server.id) },
                                    enabled = !isBusy && isHealthyAndAvailable && tierAllowed,
                                ) {
                                    Text(
                                        if (!tierAllowed) "Requires Premium"
                                        else "Select ${server.id}",
                                    )
                                }
                            }
                        }
                    }
                }
            }
        } else if (serversLoaded && !serversLoading) {
            Spacer(Modifier.height(8.dp))
            Text("No enabled VPN servers reported by control plane.")
        }

        Spacer(Modifier.height(16.dp))
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("Privacy & Advertising Choice", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "TunnelPilot operates on a strict Zero-Log policy. Network traffic inside the VPN tunnel is never inspected, recorded, or shared with advertisers.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = onReviewPrivacyChoices,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Review Privacy & Ad Choices")
                }
            }
        }
    }
}

@Composable
private fun ConfigSection(
    configPresent: Boolean,
    provisioningState: ProvisioningState,
    onSave: (String) -> Result<Unit>,
    onClear: () -> Unit,
    onForceClearLocal: () -> Unit,
) {
    var text by rememberSaveable { mutableStateOf("") }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    val hasProvisioningError = when (provisioningState) {
        is ProvisioningState.Provisioned -> provisioningState.lastError != null
        is ProvisioningState.Error -> true
        else -> false
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        Text("WireGuard configuration", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(8.dp))
        Text(
            if (configPresent) "Configuration is stored encrypted with Android Keystore."
            else "Import a WireGuard client config. Do not paste production keys into chat or Git.",
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            Modifier.fillMaxWidth(),
            minLines = 12,
            label = { Text("[Interface] / [Peer]") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            visualTransformation = VisualTransformation.None,
        )
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                val result = onSave(text)
                message = result.fold({ "Configuration saved and validated." }, { it.message ?: "Invalid configuration" })
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = text.isNotBlank(),
        ) { Text("Save configuration") }
        if (configPresent) {
            Spacer(Modifier.height(8.dp))
            TextButton(
                onClick = {
                    onClear()
                    text = ""
                    message = "Requested configuration removal."
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Delete saved configuration") }
            if (hasProvisioningError) {
                TextButton(
                    onClick = {
                        onForceClearLocal()
                        text = ""
                        message = "Local configuration removed without server revocation."
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "Force delete local configuration (offline / skip server revoke)",
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
        message?.let {
            Spacer(Modifier.height(8.dp))
            Text(it)
        }
    }
}

private fun stateLabel(state: VpnState): String = when (state) {
    VpnState.Disconnected -> "Disconnected"
    VpnState.Connecting -> "Connecting…"
    is VpnState.Connected -> "Connected"
    is VpnState.Error -> "Error"
}

private fun provisioningSummary(state: ProvisioningState, configPresent: Boolean): String = when (state) {
    is ProvisioningState.Provisioned -> "Configuration: Provisioned (${state.clientAddress})"
    ProvisioningState.Provisioning -> "Configuration: Provisioning in progress…"
    is ProvisioningState.Error -> if (configPresent) {
        "Configuration: Stored locally (last operation failed)"
    } else {
        "Configuration: Not provisioned (${state.message})"
    }
    ProvisioningState.NotConfigured -> if (configPresent) {
        "Configuration: Stored locally"
    } else {
        "Configuration: Not configured"
    }
}

private fun routingDescription(mode: RoutingMode, selectedCount: Int): String = when (mode) {
    RoutingMode.ALL_APPS -> "All applications use the VPN tunnel."
    RoutingMode.SELECTED_APPS -> "$selectedCount selected app(s) use the VPN; other apps keep their normal network route."
}

private fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var index = -1
    while (value >= 1024 && index < units.lastIndex) {
        value /= 1024
        index++
    }
    return String.format(Locale.US, "%.1f %s", value, units[index])
}

internal fun isBrowserPackage(packageName: String, label: String): Boolean {
    val pkg = packageName.lowercase(Locale.US)
    val lbl = label.lowercase(Locale.US)
    return pkg.contains("browser") ||
        pkg.contains("chrome") ||
        pkg.contains("firefox") ||
        pkg.contains("mozilla") ||
        pkg.contains("brave") ||
        pkg.contains("opera") ||
        pkg.contains("duckduckgo") ||
        pkg.contains("vivaldi") ||
        lbl.contains("browser")
}

internal fun isMessengerPackage(packageName: String, label: String): Boolean {
    val pkg = packageName.lowercase(Locale.US)
    val lbl = label.lowercase(Locale.US)
    return pkg.contains("telegram") ||
        pkg.contains("whatsapp") ||
        pkg.contains("signal") ||
        pkg.contains("discord") ||
        pkg.contains("messenger") ||
        pkg.contains("viber") ||
        pkg.contains("slack") ||
        pkg.contains("element") ||
        lbl.contains("telegram") ||
        lbl.contains("whatsapp") ||
        lbl.contains("signal") ||
        lbl.contains("discord")
}

internal fun isMediaPackage(packageName: String, label: String): Boolean {
    val pkg = packageName.lowercase(Locale.US)
    val lbl = label.lowercase(Locale.US)
    return pkg.contains("youtube") ||
        pkg.contains("spotify") ||
        pkg.contains("netflix") ||
        pkg.contains("twitch") ||
        pkg.contains("music") ||
        pkg.contains("video") ||
        pkg.contains("plex") ||
        lbl.contains("youtube") ||
        lbl.contains("spotify")
}
