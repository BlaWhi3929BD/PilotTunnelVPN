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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardOptions
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<MainViewModel>()

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (it.resultCode == RESULT_OK) viewModel.connect()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    TunnelPilotScreen(
                        viewModel = viewModel,
                        requestVpnPermission = {
                            val intent: Intent? = viewModel.requiredVpnPermissionIntent()
                            if (intent != null) vpnPermissionLauncher.launch(intent)
                            else viewModel.connect()
                        },
                    )
                }
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun TunnelPilotScreen(
    viewModel: MainViewModel,
    requestVpnPermission: () -> Unit,
) {
    var section by remember { mutableStateOf("VPN") }
    val state by viewModel.state.collectAsState()
    val configPresent by viewModel.configPresent.collectAsState()
    val apps by viewModel.installedApps.collectAsState()
    val selectedApps by viewModel.selectedApps.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
    ) {
        Text("TunnelPilot", style = MaterialTheme.typography.headlineMedium)
        Text("Android VPN MVP", style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(16.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("VPN", "Apps", "Config").forEach { item ->
                if (section == item) {
                    Button(onClick = { section = item }) { Text(item) }
                } else {
                    OutlinedButton(onClick = { section = item }) { Text(item) }
                }
            }
        }
        Spacer(Modifier.height(16.dp))

        when (section) {
            "VPN" -> {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Text(stateLabel(state), style = MaterialTheme.typography.titleLarge)
                        Spacer(Modifier.height(8.dp))
                        Text(
                            if (selectedApps.isEmpty()) {
                                "All applications use the tunnel."
                            } else {
                                "Auto-VPN allow-list: ${selectedApps.size} app(s)"
                            },
                        )
                        Spacer(Modifier.height(16.dp))
                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            onClick = requestVpnPermission,
                            enabled = configPresent && state !is VpnState.Connecting && state !is VpnState.Connected,
                        ) { Text("Connect") }
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(
                            modifier = Modifier.fillMaxWidth(),
                            onClick = viewModel::disconnect,
                            enabled = state is VpnState.Connected,
                        ) { Text("Disconnect") }
                        if (state is VpnState.Error) {
                            Spacer(Modifier.height(8.dp))
                            Text(
                                text = (state as VpnState.Error).message,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                }
            }
            "Apps" -> {
                Text("Apps routed through VPN", style = MaterialTheme.typography.titleLarge)
                Text("Select apps for the Auto-VPN mode. Empty selection means all apps.")
                Spacer(Modifier.height(8.dp))
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(apps, key = { it.packageName }) { app ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = app.packageName in selectedApps,
                                onCheckedChange = { viewModel.toggleApp(app.packageName) },
                            )
                            Column(modifier = Modifier.weight(1f)) {
                                Text(app.label)
                                Text(app.packageName, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                        HorizontalDivider()
                    }
                }
            }
            "Config" -> {
                ConfigSection(
                    configPresent = configPresent,
                    onSave = { viewModel.setConfig(it) },
                    onClear = viewModel::clearConfig,
                )
            }
        }
    }
}

@androidx.compose.runtime.Composable
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
            if (configPresent) {
                "A config is stored locally using Android Keystore encryption. Re-importing replaces it."
            } else {
                "Paste a client WireGuard configuration. Never paste a production private key into chat or commit it to Git."
            },
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f, fill = false),
            minLines = 12,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            visualTransformation = VisualTransformation.None,
            label = { Text("[Interface] / [Peer] config") },
        )
        Spacer(Modifier.height(12.dp))
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                val result = onSave(text)
                message = result.fold({ "Config saved." }, { it.message ?: "Invalid config" })
            },
            enabled = text.isNotBlank(),
        ) { Text("Save config") }
        if (configPresent) {
            Spacer(Modifier.height(8.dp))
            TextButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    onClear()
                    text = ""
                    message = "Saved config removed."
                },
            ) { Text("Delete saved config") }
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
    VpnState.Connected -> "Connected"
    is VpnState.Error -> "Error"
}
