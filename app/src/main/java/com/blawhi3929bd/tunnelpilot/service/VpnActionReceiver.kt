package com.blawhi3929bd.tunnelpilot.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.blawhi3929bd.tunnelpilot.TunnelPilotController

class VpnActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == ACTION_DISCONNECT) {
            val controller = TunnelPilotController.getInstance(context)
            controller.disconnect()
        }
    }

    companion object {
        const val ACTION_DISCONNECT = "com.blawhi3929bd.tunnelpilot.ACTION_DISCONNECT"
    }
}
