package com.blawhi3929bd.tunnelpilot

sealed interface VpnState {
    data object Disconnected : VpnState
    data object Connecting : VpnState
    data class Connected(
        val rxBytes: Long = 0L,
        val txBytes: Long = 0L,
    ) : VpnState
    data class Error(val message: String) : VpnState
}

fun VpnState.isActive(): Boolean = this is VpnState.Connected || this is VpnState.Connecting
