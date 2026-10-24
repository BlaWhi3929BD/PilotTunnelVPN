package com.blawhi3929bd.tunnelpilot.service

import org.junit.Assert.assertEquals
import org.junit.Test

class VpnNotificationManagerTest {

    @Test
    fun formatBytes_formatsZeroAndSmallBytes() {
        assertEquals("0 B", AndroidVpnNotificationManager.formatBytes(0))
        assertEquals("0 B", AndroidVpnNotificationManager.formatBytes(-5))
        assertEquals("512 B", AndroidVpnNotificationManager.formatBytes(512))
        assertEquals("1023 B", AndroidVpnNotificationManager.formatBytes(1023))
    }

    @Test
    fun formatBytes_formatsKilobytes() {
        assertEquals("1.0 KB", AndroidVpnNotificationManager.formatBytes(1024))
        assertEquals("1.5 KB", AndroidVpnNotificationManager.formatBytes(1536))
        assertEquals("500.0 KB", AndroidVpnNotificationManager.formatBytes(512000))
    }

    @Test
    fun formatBytes_formatsMegabytesAndGigabytes() {
        assertEquals("1.0 MB", AndroidVpnNotificationManager.formatBytes(1024 * 1024))
        assertEquals("15.5 MB", AndroidVpnNotificationManager.formatBytes((15.5 * 1024 * 1024).toLong()))
        assertEquals("1.0 GB", AndroidVpnNotificationManager.formatBytes(1024L * 1024 * 1024))
        assertEquals("2.5 GB", AndroidVpnNotificationManager.formatBytes((2.5 * 1024 * 1024 * 1024).toLong()))
    }

    @Test
    fun noOpNotificationManager_executesSafely() {
        val noOp = NoOpVpnNotificationManager()
        noOp.showConnectingNotification()
        noOp.showConnectedNotification("srv-1", 100, 200)
        noOp.dismissNotification()
        // No exception thrown
    }
}
