package com.blawhi3929bd.tunnelpilot

import org.junit.Assert.assertTrue
import org.junit.Test

class VpnStateTest {
    @Test
    fun disconnected_is_not_connected() {
        assertTrue(VpnState.Disconnected !is VpnState.Connected)
    }
}
