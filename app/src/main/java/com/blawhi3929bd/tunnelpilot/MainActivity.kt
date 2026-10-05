package com.blawhi3929bd.tunnelpilot

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<MainViewModel>()

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (it.resultCode == RESULT_OK) {
            viewModel.connect()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val state by viewModel.state.collectAsState()
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Text("TunnelPilot", style = MaterialTheme.typography.headlineMedium)
                        Spacer(Modifier.height(8.dp))
                        Text(stateLabel(state))
                        Spacer(Modifier.height(24.dp))

                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            onClick = {
                                val intent: Intent? = viewModel.requiredVpnPermissionIntent()
                                if (intent != null) {
                                    vpnPermissionLauncher.launch(intent)
                                } else {
                                    viewModel.connect()
                                }
                            },
                            enabled = state !is VpnState.Connecting && state !is VpnState.Connected,
                        ) {
                            Text("Connect")
                        }
                        Spacer(Modifier.height(12.dp))
                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            onClick = viewModel::disconnect,
                            enabled = state is VpnState.Connected,
                        ) {
                            Text("Disconnect")
                        }
                    }
                }
            }
        }
    }

    private fun stateLabel(state: VpnState): String = when (state) {
        VpnState.Disconnected -> "Disconnected"
        VpnState.Connecting -> "Connecting…"
        VpnState.Connected -> "Connected"
        is VpnState.Error -> "Error: ${state.message}"
    }
}
