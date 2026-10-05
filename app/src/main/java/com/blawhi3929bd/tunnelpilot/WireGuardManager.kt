package com.blawhi3929bd.tunnelpilot

import android.content.Context
import com.wireguard.android.backend.Backend
import com.wireguard.android.backend.BackendException
import com.wireguard.android.backend.GoBackend
import com.wireguard.config.Config
import com.wireguard.android.backend.Tunnel
import java.io.ByteArrayInputStream

/**
 * Owns the local WireGuard backend.
 *
 * No credentials are hard-coded here. A production build will receive a
 * server-specific WireGuard config from the authenticated control plane.
 */
class WireGuardManager(context: Context) {
    private val backend: Backend = GoBackend(context.applicationContext)
    private val tunnel = WireGuardTunnel { state ->
        // State callbacks are handled by the caller via connect/disconnect.
        lastState = state
    }

    @Volatile
    private var lastState: Tunnel.State = Tunnel.State.DOWN

    fun connect(configText: String) {
        val config = Config.parse(ByteArrayInputStream(configText.toByteArray(Charsets.UTF_8)))
        try {
            backend.setState(tunnel, Tunnel.State.UP, config)
        } catch (e: BackendException) {
            throw e
        }
    }

    fun disconnect() {
        backend.setState(tunnel, Tunnel.State.DOWN, null)
    }

    fun currentState(): Tunnel.State = lastState
}
