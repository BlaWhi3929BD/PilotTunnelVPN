package com.blawhi3929bd.tunnelpilot.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.blawhi3929bd.tunnelpilot.TunnelPilotController

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED ||
            intent?.action == "android.intent.action.QUICKBOOT_POWERON"
        ) {
            val controller = TunnelPilotController.getInstance(context)
            if (controller.autoConnectOnBoot.value && controller.configPresent.value) {
                controller.connect()
            }
        }
    }
}
