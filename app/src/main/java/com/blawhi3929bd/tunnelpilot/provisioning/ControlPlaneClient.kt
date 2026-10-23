package com.blawhi3929bd.tunnelpilot.provisioning

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

interface ControlPlaneApi {
    fun registerDevice(
        deviceId: String,
        publicKey: String,
        appVersion: String,
        deviceToken: String? = null,
    ): RegistrationResult

    fun rotateDevice(
        deviceId: String,
        publicKey: String,
        appVersion: String,
        deviceToken: String,
    ): RotationResult

    fun revokeDevice(
        deviceId: String,
        deviceToken: String,
    ): Boolean

    fun listServers(): List<RegisteredServer>
}

class ControlPlaneHttpException(
    val statusCode: Int,
    message: String,
) : IllegalStateException(message)

class ControlPlaneClient(
    private val baseUrl: String,
    private val connectTimeoutMs: Int = 8_000,
    private val readTimeoutMs: Int = 8_000,
    private val allowCleartext: Boolean = true,
) : ControlPlaneApi {
    override fun registerDevice(
        deviceId: String,
        publicKey: String,
        appVersion: String,
        deviceToken: String?,
    ): RegistrationResult {
        require(deviceId.isNotBlank()) { "Device ID is required" }
        require(publicKey.isNotBlank()) { "WireGuard public key is required" }
        require(appVersion.isNotBlank()) { "App version is required" }

        val url = endpoint("/v1/devices")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
            if (!deviceToken.isNullOrBlank()) {
                setRequestProperty("X-Device-Token", deviceToken)
            }
        }

        return try {
            val payload = JSONObject()
                .put("device_id", deviceId)
                .put("client_public_key", publicKey)
                .put("app_version", appVersion)
                .toString()

            connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                writer.write(payload)
            }

            val responseCode = connection.responseCode
            val responseBody = readResponseBody(connection, responseCode)
            if (responseCode !in 200..299) {
                throw ControlPlaneHttpException(responseCode, parseError(responseBody, responseCode))
            }

            parseRegistration(responseBody)
        } finally {
            connection.disconnect()
        }
    }


    override fun rotateDevice(
        deviceId: String,
        publicKey: String,
        appVersion: String,
        deviceToken: String,
    ): RotationResult {
        require(deviceId.isNotBlank()) { "Device ID is required" }
        require(publicKey.isNotBlank()) { "WireGuard public key is required" }
        require(appVersion.isNotBlank()) { "App version is required" }
        require(deviceToken.isNotBlank()) { "Device token is required" }

        val url = endpoint("/v1/devices/$deviceId/rotate")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-Device-Token", deviceToken)
        }

        return try {
            val payload = JSONObject()
                .put("client_public_key", publicKey)
                .put("app_version", appVersion)
                .toString()

            connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                writer.write(payload)
            }

            val responseCode = connection.responseCode
            val responseBody = readResponseBody(connection, responseCode)
            if (responseCode !in 200..299) {
                throw ControlPlaneHttpException(responseCode, parseError(responseBody, responseCode))
            }

            parseRotation(responseBody)
        } finally {
            connection.disconnect()
        }
    }

    override fun revokeDevice(
        deviceId: String,
        deviceToken: String,
    ): Boolean {
        require(deviceId.isNotBlank()) { "Device ID is required" }
        require(deviceToken.isNotBlank()) { "Device token is required" }

        val url = endpoint("/v1/devices/$deviceId")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "DELETE"
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-Device-Token", deviceToken)
        }

        return try {
            val responseCode = connection.responseCode
            if (responseCode !in 200..299 && responseCode != 404) {
                val responseBody = readResponseBody(connection, responseCode)
                throw ControlPlaneHttpException(responseCode, parseError(responseBody, responseCode))
            }
            true
        } finally {
            connection.disconnect()
        }
    }

    override fun listServers(): List<RegisteredServer> {
        val url = endpoint("/v1/servers")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
            setRequestProperty("Accept", "application/json")
        }

        return try {
            val responseCode = connection.responseCode
            val responseBody = readResponseBody(connection, responseCode)
            if (responseCode !in 200..299) {
                throw ControlPlaneHttpException(responseCode, parseError(responseBody, responseCode))
            }
            val array = runCatching { JSONArray(responseBody) }.getOrElse {
                throw IllegalStateException("Invalid server catalog response from control plane", it)
            }
            buildList(array.length()) {
                for (i in 0 until array.length()) {
                    add(parseServer(array.getJSONObject(i)))
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun endpoint(path: String): URL {
        val normalized = baseUrl.trim().removeSuffix("/")
        require(normalized.isNotBlank()) { "Control plane URL is required" }
        val parsed = URI(normalized)
        val scheme = parsed.scheme?.lowercase()
        require(scheme == "http" || scheme == "https") {
            "Control plane URL must use http or https"
        }
        val host = parsed.host?.lowercase().orEmpty()
        if (!allowCleartext && scheme == "http" && host !in LOOPBACK_HOSTS) {
            throw IllegalArgumentException("HTTPS is required for Control Plane URL in release builds")
        }
        return URI("$normalized$path").toURL()
    }

    private fun readResponseBody(connection: HttpURLConnection, responseCode: Int): String {
        val stream = if (responseCode in 200..299) connection.inputStream else connection.errorStream
        if (stream == null) return ""
        return BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
    }

    private fun parseError(body: String, responseCode: Int): String {
        val detail = runCatching { JSONObject(body).optString("detail") }.getOrNull().orEmpty()
        return detail.ifBlank { "Control plane request failed (HTTP $responseCode)" }
    }


    private fun parseServer(serverJson: JSONObject): RegisteredServer {
        val id = serverJson.optString("id").trim()
        val region = serverJson.optString("region").trim()
        val hostname = serverJson.optString("hostname").trim()
        val publicKey = serverJson.optString("public_key").trim()
        val port = serverJson.optInt("port", -1)
        require(id.isNotEmpty()) { "Server id is missing in response" }
        require(region.isNotEmpty()) { "Server region is missing in response" }
        require(hostname.isNotEmpty()) { "Server hostname is missing in response" }
        require(publicKey.isNotEmpty()) { "Server public_key is missing in response" }
        require(port in 1..65535) { "Server port is invalid: $port" }

        val peerCount = if (serverJson.has("peer_count") && !serverJson.isNull("peer_count")) {
            serverJson.getInt("peer_count").coerceAtLeast(0)
        } else {
            null
        }
        val peerCapacity = if (serverJson.has("peer_capacity") && !serverJson.isNull("peer_capacity")) {
            serverJson.getInt("peer_capacity").coerceAtLeast(0)
        } else {
            null
        }
        val capacityRemaining = if (serverJson.has("capacity_remaining") && !serverJson.isNull("capacity_remaining")) {
            serverJson.getInt("capacity_remaining").coerceAtLeast(0)
        } else if (peerCapacity != null && peerCount != null) {
            (peerCapacity - peerCount).coerceAtLeast(0)
        } else {
            null
        }

        return RegisteredServer(
            id = id,
            region = region,
            hostname = hostname,
            publicKey = publicKey,
            port = port,
            healthStatus = serverJson.optString("health_status", "unknown").trim().ifBlank { "unknown" },
            peerCount = peerCount,
            peerCapacity = peerCapacity,
            capacityRemaining = capacityRemaining,
        )
    }

    private fun parseRotation(body: String): RotationResult {
        val json = JSONObject(body)
        val serverJson = json.getJSONObject("server")
        return RotationResult(
            status = json.getString("status"),
            deviceId = json.getString("device_id"),
            clientAddress = json.getString("client_address"),
            provisioned = json.getBoolean("provisioned"),
            server = parseServer(serverJson),
        )
    }

    private fun parseRegistration(body: String): RegistrationResult {
        val json = JSONObject(body)
        val serverJson = json.getJSONObject("server")
        val rawToken = if (json.isNull("device_token")) {
            null
        } else {
            json.optString("device_token").trim().takeIf { it.isNotEmpty() && !it.equals("null", ignoreCase = true) }
        }
        return RegistrationResult(
            deviceId = json.getString("device_id"),
            clientAddress = json.getString("client_address"),
            provisioned = json.getBoolean("provisioned"),
            server = parseServer(serverJson),
            deviceToken = rawToken,
        )
    }

    private companion object {
        val LOOPBACK_HOSTS = setOf("127.0.0.1", "localhost", "::1", "[::1]")
    }
}
