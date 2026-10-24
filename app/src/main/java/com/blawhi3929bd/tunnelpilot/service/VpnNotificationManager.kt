package com.blawhi3929bd.tunnelpilot.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.blawhi3929bd.tunnelpilot.MainActivity
import com.blawhi3929bd.tunnelpilot.R
import java.util.Locale

interface VpnNotificationProvider {
    fun showConnectedNotification(serverId: String?, rxBytes: Long, txBytes: Long)
    fun showConnectingNotification()
    fun dismissNotification()
}

class NoOpVpnNotificationManager : VpnNotificationProvider {
    override fun showConnectedNotification(serverId: String?, rxBytes: Long, txBytes: Long) {}
    override fun showConnectingNotification() {}
    override fun dismissNotification() {}
}

class AndroidVpnNotificationManager(
    private val context: Context,
) : VpnNotificationProvider {
    private val notificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    init {
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "TunnelPilot VPN Status",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Shows active VPN connection status and traffic stats"
                setShowBadge(false)
            }
            notificationManager.createNotificationChannel(channel)
        }
    }

    override fun showConnectingNotification() {
        val contentIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle("TunnelPilot: Connecting...")
            .setContentText("Establishing encrypted WireGuard tunnel")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(contentIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        try {
            notificationManager.notify(NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // Android 13+ when POST_NOTIFICATIONS is not granted
        }
    }

    override fun showConnectedNotification(serverId: String?, rxBytes: Long, txBytes: Long) {
        val contentIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val disconnectIntent = Intent(context, VpnActionReceiver::class.java).apply {
            action = VpnActionReceiver.ACTION_DISCONNECT
        }
        val disconnectPendingIntent = PendingIntent.getBroadcast(
            context,
            1,
            disconnectIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val serverLabel = serverId?.let { "Server: $it" } ?: "Connected"
        val statsText = "⬇ ${formatBytes(rxBytes)}   ⬆ ${formatBytes(txBytes)}"

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle("TunnelPilot: $serverLabel")
            .setContentText(statsText)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(contentIntent)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Disconnect",
                disconnectPendingIntent,
            )
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        try {
            notificationManager.notify(NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // Android 13+ when POST_NOTIFICATIONS is not granted
        }
    }

    override fun dismissNotification() {
        notificationManager.cancel(NOTIFICATION_ID)
    }

    companion object {
        const val CHANNEL_ID = "tunnelpilot_vpn_status"
        const val NOTIFICATION_ID = 1001

        fun formatBytes(bytes: Long): String {
            if (bytes <= 0) return "0 B"
            if (bytes < 1024) return "$bytes B"
            val exp = (Math.log(bytes.toDouble()) / Math.log(1024.0)).toInt()
            val pre = "KMGTPE"[exp - 1]
            return String.format(Locale.US, "%.1f %cB", bytes / Math.pow(1024.0, exp.toDouble()), pre)
        }
    }
}
