package com.blawhi3929bd.tunnelpilot.service

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.blawhi3929bd.tunnelpilot.TunnelPilotController
import com.blawhi3929bd.tunnelpilot.VpnState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch

class TunnelPilotTileService : TileService() {
    private val scope = CoroutineScope(Dispatchers.Main + Job())
    private var stateJob: Job? = null

    override fun onStartListening() {
        super.onStartListening()
        val controller = TunnelPilotController.getInstance(this)
        updateTile(controller.state.value)
        stateJob?.cancel()
        stateJob = controller.state.onEach { state ->
            updateTile(state)
        }.launchIn(scope)
    }

    override fun onStopListening() {
        super.onStopListening()
        stateJob?.cancel()
        stateJob = null
    }

    override fun onClick() {
        super.onClick()
        val controller = TunnelPilotController.getInstance(this)
        scope.launch {
            when (controller.state.value) {
                is VpnState.Connected, VpnState.Connecting -> controller.disconnectNow()
                is VpnState.Disconnected, is VpnState.Error -> controller.connectNow()
            }
        }
    }

    private fun updateTile(state: VpnState) {
        val tile = qsTile ?: return
        when (state) {
            is VpnState.Connected -> {
                tile.state = Tile.STATE_ACTIVE
                tile.label = "TunnelPilot"
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    tile.subtitle = "Connected"
                }
            }
            is VpnState.Connecting -> {
                tile.state = Tile.STATE_UNAVAILABLE
                tile.label = "TunnelPilot"
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    tile.subtitle = "Connecting..."
                }
            }
            is VpnState.Disconnected, is VpnState.Error -> {
                tile.state = Tile.STATE_INACTIVE
                tile.label = "TunnelPilot"
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    tile.subtitle = "Disconnected"
                }
            }
        }
        tile.updateTile()
    }
}
