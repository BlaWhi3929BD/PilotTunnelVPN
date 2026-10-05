package com.blawhi3929bd.tunnelpilot

import android.app.Application
import android.content.Intent
import android.net.VpnService
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.blawhi3929bd.tunnelpilot.data.InstalledApp
import com.blawhi3929bd.tunnelpilot.data.InstalledAppsRepository
import com.blawhi3929bd.tunnelpilot.data.SecureConfigStore
import com.wireguard.android.backend.BackendException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val appContext = application.applicationContext
    private val manager = WireGuardManager(appContext)
    private val configStore = SecureConfigStore(appContext)
    private val installedAppsRepository = InstalledAppsRepository(appContext)

    private val _state = MutableStateFlow<VpnState>(VpnState.Disconnected)
    val state: StateFlow<VpnState> = _state.asStateFlow()

    private val _configPresent = MutableStateFlow(configStore.load() != null)
    val configPresent: StateFlow<Boolean> = _configPresent.asStateFlow()

    private val _installedApps = MutableStateFlow<List<InstalledApp>>(emptyList())
    val installedApps: StateFlow<List<InstalledApp>> = _installedApps.asStateFlow()

    private val _selectedApps = MutableStateFlow<Set<String>>(emptySet())
    val selectedApps: StateFlow<Set<String>> = _selectedApps.asStateFlow()

    init {
        refreshInstalledApps()
    }

    fun requiredVpnPermissionIntent(): Intent? = VpnService.prepare(appContext)

    fun refreshInstalledApps() {
        viewModelScope.launch(Dispatchers.Default) {
            _installedApps.value = installedAppsRepository.getLaunchableApps()
        }
    }

    fun setConfig(rawConfig: String): Result<Unit> = runCatching {
        require(rawConfig.contains("[Interface]", ignoreCase = true)) {
            "WireGuard config must contain an [Interface] section"
        }
        require(rawConfig.contains("PrivateKey", ignoreCase = true)) {
            "WireGuard config must contain an interface PrivateKey"
        }
        require(rawConfig.contains("[Peer]", ignoreCase = true)) {
            "WireGuard config must contain at least one [Peer]"
        }
        configStore.save(rawConfig)
        _configPresent.value = true
    }

    fun clearConfig() {
        configStore.clear()
        _configPresent.value = false
        _selectedApps.value = emptySet()
        _state.value = VpnState.Disconnected
    }

    fun toggleApp(packageName: String) {
        _selectedApps.value = buildSet {
            addAll(_selectedApps.value)
            if (!add(packageName)) remove(packageName)
        }
    }

    fun connect() {
        if (!_configPresent.value) {
            _state.value = VpnState.Error("Import a WireGuard config first")
            return
        }
        if (requiredVpnPermissionIntent() != null) {
            _state.value = VpnState.Error("VPN permission is required")
            return
        }

        val rawConfig = configStore.load()
        if (rawConfig == null) {
            _state.value = VpnState.Error("Saved VPN config is unavailable")
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _state.value = VpnState.Connecting
            try {
                val config = ConfigEditor.withIncludedApplications(rawConfig, _selectedApps.value)
                manager.connect(config)
                _state.value = VpnState.Connected
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
