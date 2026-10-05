package com.blawhi3929bd.tunnelpilot

import android.app.Application
import android.content.Intent
import android.net.VpnService
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.wireguard.android.backend.BackendException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val manager = WireGuardManager(application)
    private val _state = MutableStateFlow<VpnState>(VpnState.Disconnected)
    val state: StateFlow<VpnState> = _state.asStateFlow()

    /**
     * Placeholder until the control plane returns a real server configuration.
     * Never ship a real private key inside the APK.
     */
    private val noServerConfigMessage =
        "VPN server is not configured yet. The control plane will provide a device-specific WireGuard configuration."

    fun requiredVpnPermissionIntent(): Intent? =
        VpnService.prepare(getApplication())

    fun connect() {
        if (VpnService.prepare(getApplication()) != null) {
            _state.value = VpnState.Error("VPN permission is required")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _state.value = VpnState.Connecting
            try {
                // Intentionally fail closed until a trusted control-plane config exists.
                error(noServerConfigMessage)
                // manager.connect(configText)
                // _state.value = VpnState.Connected
            } catch (e: BackendException) {
                _state.value = VpnState.Error(e.message ?: "WireGuard backend error")
            } catch (e: Exception) {
                _state.value = VpnState.Error(e.message ?: "Unable to connect")
            }
        }
    }

    fun disconnect() {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                manager.disconnect()
                _state.value = VpnState.Disconnected
            } catch (e: Exception) {
                _state.value = VpnState.Error(e.message ?: "Unable to disconnect")
            }
        }
    }
}
