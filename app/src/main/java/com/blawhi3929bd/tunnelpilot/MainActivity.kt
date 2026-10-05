package com.blawhi3929bd.tunnelpilot

import android.content.Intent
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
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import com.blawhi3929bd.tunnelpilot.provisioning.ProvisioningState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<MainViewModel>()

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        if (it.resultCode == RESULT_OK) viewModel.connect()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
}

@Composable
private fun TunnelPilotScreen(
    viewModel: MainViewModel,
    requestVpnPermission: () -> Unit,
) {
    var section by remember { mutableStateOf("VPN") }
    val state by viewModel.state.collectAsState()
    val configPresent by viewModel.configPresent.collectAsState()
    val apps by viewModel.installedApps.collectAsState()
    val selectedApps by viewModel.selectedApps.collectAsState()
    val routingMode by viewModel.routingMode.collectAsState()
    val reconnectRequired by viewModel.reconnectRequired.collectAsState()
    val controlPlaneUrl by viewModel.controlPlaneUrl.collectAsState()
    val provisioningState by viewModel.provisioningState.collectAsState()

    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Text("TunnelPilot", style = MaterialTheme.typography.headlineMedium)
        Text("Free WireGuard VPN", style = MaterialTheme.typography.bodyMedium)
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
                routingMode = routingMode,
                selectedCount = selectedApps.size,
                reconnectRequired = reconnectRequired,
                onConnect = requestVpnPermission,
                onDisconnect = viewModel::disconnect,
                onApplyRouting = viewModel::applyRoutingChanges,
                onRoutingMode = viewModel::setRoutingMode,
            )
            "Apps" -> AppsSection(
                apps = apps,
                selectedApps = selectedApps,
                onToggle = viewModel::toggleApp,
                onRefresh = viewModel::refreshInstalledApps,
            )
            "Config" -> ConfigSection(
                configPresent = configPresent,
                onSave = viewModel::setConfig,
                onClear = viewModel::clearConfig,
            )
            "Setup" -> SetupSection(
                controlPlaneUrl = controlPlaneUrl,
                provisioningState = provisioningState,
                onControlPlaneUrl = viewModel::setControlPlaneUrl,
                onProvision = viewModel::provision,
            )
        }
    }
}

@Composable
private fun VpnSection(
    state: VpnState,
    configPresent: Boolean,
    routingMode: RoutingMode,
    selectedCount: Int,
    reconnectRequired: Boolean,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
    onApplyRouting: () -> Unit,
    onRoutingMode: (RoutingMode) -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp)) {
            Text(stateLabel(state), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(6.dp))
            Text(routingDescription(routingMode, selectedCount))
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
            Spacer(Modifier.height(16.dp))

            Button(
                onClick = onConnect,
                modifier = Modifier.fillMaxWidth(),
                enabled = configPresent && !state.isActive(),
            ) { Text("Connect") }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onDisconnect,
                modifier = Modifier.fillMaxWidth(),
                enabled = state is VpnState.Connected || state is VpnState.Connecting,
            ) { Text("Disconnect") }

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
            }
            if (state is VpnState.Error) {
                Spacer(Modifier.height(10.dp))
                Text(state.message, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun AppsSection(
    apps: List<com.blawhi3929bd.tunnelpilot.data.InstalledApp>,
    selectedApps: Set<String>,
    onToggle: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val filtered = apps.filter {
        query.isBlank() || it.label.contains(query, ignoreCase = true) || it.packageName.contains(query, ignoreCase = true)
    }

    Text("Apps allowed to use the VPN", style = MaterialTheme.typography.titleLarge)
    Text("Selected-apps mode keeps the VPN connection active, but Android routes only the selected apps through it.")
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = query,
        onValueChange = { query = it },
        Modifier.fillMaxWidth(),
        label = { Text("Search apps") },
    )
    Spacer(Modifier.height(8.dp))
    OutlinedButton(onClick = onRefresh, Modifier.fillMaxWidth()) { Text("Refresh app list") }
    Spacer(Modifier.height(8.dp))
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


@Composable
private fun SetupSection(
    controlPlaneUrl: String,
    provisioningState: ProvisioningState,
    onControlPlaneUrl: (String) -> Unit,
    onProvision: () -> Unit,
) {
    Column {
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
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        Spacer(Modifier.height(12.dp))
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = onProvision,
        ) {
            Text("Provision device")
        }
        Spacer(Modifier.height(12.dp))
        when (provisioningState) {
            ProvisioningState.NotConfigured -> Text("Not provisioned yet.")
            ProvisioningState.Provisioning -> Text("Provisioning…")
            is ProvisioningState.Provisioned -> {
                Text("Device ID: ${provisioningState.deviceId}")
                Text("VPN address: ${provisioningState.clientAddress}")
                Text("The generated configuration is stored encrypted locally.")
            }
            is ProvisioningState.Error -> {
                Text(
                    provisioningState.message,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@Composable
private fun ConfigSection(
    configPresent: Boolean,
    onSave: (String) -> Result<Unit>,
    onClear: () -> Unit,
) {
    var text by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }

    Column {
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
                    message = "Saved configuration removed."
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Delete saved configuration") }
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
