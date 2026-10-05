package com.blawhi3929bd.tunnelpilot

import android.content.Context
import com.wireguard.android.backend.Backend
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Statistics
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import java.io.ByteArrayInputStream

class WireGuardManager(context: Context) {
    private val tunnel = WireGuardTunnel { state -> lastState = state }
    private val backend: Backend = GoBackend(context.applicationContext)

    @Volatile
    private var lastState: Tunnel.State = Tunnel.State.DOWN

    fun connect(configText: String) {
        val config = Config.parse(ByteArrayInputStream(configText.toByteArray(Charsets.UTF_8)))
        backend.setState(tunnel, Tunnel.State.UP, config)
    }

    fun disconnect() {
        backend.setState(tunnel, Tunnel.State.DOWN, null)
    }

    fun currentState(): Tunnel.State = lastState

    fun statistics(): Statistics? = runCatching { backend.getStatistics(tunnel) }.getOrNull()
}
