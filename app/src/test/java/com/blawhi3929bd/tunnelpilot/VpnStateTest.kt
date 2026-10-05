package com.blawhi3929bd.tunnelpilot

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnStateTest {
    @Test
    fun only_connecting_and_connected_are_active() {
        assertTrue(VpnState.Connecting.isActive())
        assertTrue(VpnState.Connected().isActive())
        assertFalse(VpnState.Disconnected.isActive())
        assertFalse(VpnState.Error("x").isActive())
    }
}
