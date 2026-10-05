package com.blawhi3929bd.tunnelpilot

import com.wireguard.android.backend.Tunnel

class WireGuardTunnel(
    private val onStateChanged: (Tunnel.State) -> Unit,
) : Tunnel {
    override fun getName(): String = "tunnelpilot"

    override fun onStateChange(newState: Tunnel.State) {
        onStateChanged(newState)
    }
}
