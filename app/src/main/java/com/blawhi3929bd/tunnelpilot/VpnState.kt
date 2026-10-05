package com.blawhi3929bd.tunnelpilot

sealed interface VpnState {
    data object Disconnected : VpnState
    data object Connecting : VpnState
    data object Connected : VpnState
    data class Error(val message: String) : VpnState
}
