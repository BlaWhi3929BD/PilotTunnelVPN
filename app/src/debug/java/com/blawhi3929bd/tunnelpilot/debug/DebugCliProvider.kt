package com.blawhi3929bd.tunnelpilot.debug

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import android.os.Process
import com.blawhi3929bd.tunnelpilot.BuildConfig
import com.blawhi3929bd.tunnelpilot.RoutingMode
import com.blawhi3929bd.tunnelpilot.TunnelPilotController
import kotlinx.coroutines.runBlocking

/**
 * Debug-only ADB CLI endpoint invoked via:
 * `adb shell content call --uri content://com.blawhi3929bd.tunnelpilot.debug.cli --method <method> [--arg <arg>]`
 *
 * Restricted strictly to ADB shell (UID 2000), root (UID 0), or the app itself.
 * Never returns private keys or raw device tokens.
 */
class DebugCliProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        enforceShellCaller()
        val ctx = context ?: error("ContentProvider context is unavailable")
        val controller = TunnelPilotController.getInstance(ctx)

        return runBlocking {
            val actionResult: Result<String> = when (method.lowercase()) {
                "status" -> Result.success("ok")
                "set_url" -> runCatching {
                    val url = requireNotNull(arg?.trim()?.takeIf { it.isNotEmpty() }) {
                        "Missing URL argument for set_url"
                    }
                    controller.setControlPlaneUrl(url)
                    "control_plane_url updated"
                }
                "provision" -> {
                    if (!arg.isNullOrBlank()) {
                        controller.setControlPlaneUrl(arg.trim())
                    }
                    controller.provisionNow().map { "provisioned ${it.clientAddress}" }
                }
                "rotate_key" -> {
                    controller.rotateDeviceKeyNow().map { "rotated key for ${it.deviceId}" }
                }
                "migrate_server" -> {
                    val targetServerId = arg?.trim().orEmpty()
                    if (targetServerId.isEmpty()) {
                        Result.failure(IllegalArgumentException("Missing server_id argument for migrate_server"))
                    } else {
                        controller.migrateServerNow(targetServerId).map {
                            "migrated to ${it.serverId} (${it.clientAddress})"
                        }
                    }
                }
                "select_server" -> runCatching {
                    val serverId = arg?.trim()?.takeIf { it.isNotEmpty() && !it.equals("auto", ignoreCase = true) }
                    controller.setPreferredServerId(serverId)
                    "preferred_server_id=${serverId ?: "auto"}"
                }
                "select_region" -> runCatching {
                    val region = arg?.trim()?.takeIf { it.isNotEmpty() && !it.equals("auto", ignoreCase = true) }
                    controller.setPreferredRegion(region)
                    "preferred_region=${region ?: "auto"}"
                }
                "connect" -> {
                    controller.connectNow().map { "connected" }
                }
                "disconnect" -> {
                    controller.disconnectNow().map { "disconnected" }
                }
                "set_routing_mode" -> runCatching {
                    val modeName = requireNotNull(arg?.trim()?.uppercase()) {
                        "Missing routing mode (ALL_APPS or SELECTED_APPS)"
                    }
                    val mode = RoutingMode.valueOf(modeName)
                    controller.setRoutingMode(mode)
                    "routing_mode=${mode.name}"
                }
                "set_selected_apps" -> runCatching {
                    val packages = arg
                        ?.split(",")
                        ?.map { it.trim() }
                        ?.filter { it.isNotEmpty() }
                        ?.toSet()
                        .orEmpty()
                    controller.setSelectedApps(packages)
                    "selected_apps=${packages.joinToString(",")}"
                }
                "apply_routing" -> {
                    controller.applyRoutingChangesNow().map { "routing applied" }
                }
                "revoke", "clear_config" -> {
                    val forceLocal = arg?.trim()?.equals("force_local", ignoreCase = true) == true
                    controller.clearConfigNow(forceLocal = forceLocal).map {
                        if (forceLocal) "cleared local config (force_local)" else "revoked and cleared config"
                    }
                }
                "reset_identity" -> {
                    val forceLocal = arg?.trim()?.equals("force_local", ignoreCase = true) == true
                    controller.resetIdentityNow(forceLocal = forceLocal).map { newId ->
                        "reset_identity new_device_id=$newId"
                    }
                }
                "check_servers", "servers" -> {
                    controller.refreshServersNow().map { list ->
                        list.joinToString(";") { srv ->
                            "${srv.id}[${srv.region}/${srv.tier}]:${srv.healthStatus}(${srv.peerCount ?: 0}/${srv.peerCapacity ?: 0})"
                        }.ifEmpty { "no_servers" }
                    }
                }
                "probe_http" -> runCatching {
                    val targetUrl = requireNotNull(arg?.trim()?.takeIf { it.isNotEmpty() }) {
                        "Missing URL argument for probe_http"
                    }
                    val conn = (java.net.URI(targetUrl).toURL().openConnection() as java.net.HttpURLConnection).apply {
                        requestMethod = "GET"
                        connectTimeout = 2_500
                        readTimeout = 2_500
                    }
                    try {
                        val code = conn.responseCode
                        val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText().trim() }
                        "http_status=$code body=$body app_uid=${Process.myUid()}"
                    } finally {
                        conn.disconnect()
                    }
                }
                else -> Result.failure(IllegalArgumentException("Unknown CLI method: $method"))
            }

            val snapshot = controller.statusSnapshot()
            Bundle().apply {
                putBoolean("ok", actionResult.isSuccess)
                putString(
                    "message",
                    actionResult.getOrElse { it.message ?: "Command failed" },
                )
                putString("vpn_state", snapshot.vpnState)
                putLong("rx_bytes", snapshot.rxBytes)
                putLong("tx_bytes", snapshot.txBytes)
                putBoolean("config_present", snapshot.configPresent)
                putString("routing_mode", snapshot.routingMode)
                putString("selected_apps", snapshot.selectedApps.sorted().joinToString(","))
                putBoolean("reconnect_required", snapshot.reconnectRequired)
                putString("control_plane_url", snapshot.controlPlaneUrl)
                putString("provisioning_status", snapshot.provisioningStatus)
                putString("device_id", snapshot.deviceId)
                putString("client_address", snapshot.clientAddress ?: "")
                putString("assigned_server_id", snapshot.assignedServerId ?: "")
                putString("preferred_server_id", snapshot.preferredServerId ?: "")
                putString("preferred_region", snapshot.preferredRegion ?: "")
                putString("device_tier", snapshot.deviceTier)
                putBoolean("has_device_token", snapshot.hasDeviceToken)
                putBoolean("vpn_permission_required", snapshot.vpnPermissionRequired)
                snapshot.errorMessage?.let { putString("error", it) }
            }
        }
    }

    private fun enforceShellCaller() {
        check(BuildConfig.DEBUG) { "DebugCliProvider is only available in debug builds" }
        val uid = Binder.getCallingUid()
        if (!isAllowedCallerUid(uid = uid, appUid = Process.myUid(), isDebugBuild = BuildConfig.DEBUG)) {
            throw SecurityException("DebugCliProvider is restricted to ADB shell (caller uid=$uid)")
        }
    }

    companion object {
        private const val ROOT_UID = 0
        private const val SHELL_UID = 2000

        internal fun isAllowedCallerUid(uid: Int, appUid: Int, isDebugBuild: Boolean): Boolean {
            if (!isDebugBuild) return false
            return uid == SHELL_UID || uid == ROOT_UID || uid == appUid
        }
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0
}
