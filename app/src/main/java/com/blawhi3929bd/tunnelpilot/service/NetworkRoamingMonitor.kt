package com.blawhi3929bd.tunnelpilot.service

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest

interface NetworkRoamingMonitor {
    fun start(onNetworkChanged: () -> Unit)
    fun stop()
}

class NoOpNetworkRoamingMonitor : NetworkRoamingMonitor {
    override fun start(onNetworkChanged: () -> Unit) {}
    override fun stop() {}
}

class AndroidNetworkRoamingMonitor(
    private val context: Context,
) : NetworkRoamingMonitor {
    private var callback: ConnectivityManager.NetworkCallback? = null
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
    private var lastActiveNetwork: Network? = null

    override fun start(onNetworkChanged: () -> Unit) {
        if (callback != null || connectivityManager == null) return
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                val previous = lastActiveNetwork
                lastActiveNetwork = network
                if (previous != null && previous != network) {
                    onNetworkChanged()
                }
            }

            override fun onLost(network: Network) {
                if (lastActiveNetwork == network) {
                    lastActiveNetwork = null
                    onNetworkChanged()
                }
            }
        }
        callback = cb
        try {
            connectivityManager.registerNetworkCallback(request, cb)
        } catch (_: Exception) {
            // Ignore if restricted ROM / security policy prevents registration
        }
    }

    override fun stop() {
        val cb = callback ?: return
        callback = null
        lastActiveNetwork = null
        try {
            connectivityManager?.unregisterNetworkCallback(cb)
        } catch (_: Exception) {
        }
    }
}
