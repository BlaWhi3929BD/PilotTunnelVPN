package com.blawhi3929bd.tunnelpilot.provisioning

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class ControlPlaneClient(
    private val baseUrl: String,
    private val connectTimeoutMs: Int = 8_000,
    private val readTimeoutMs: Int = 8_000,
) {
    fun registerDevice(
        deviceId: String,
        publicKey: String,
        appVersion: String,
        deviceToken: String? = null,
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
                throw IllegalStateException(parseError(responseBody, responseCode))
            }

            parseRegistration(responseBody)
        } finally {
            connection.disconnect()
        }
    }


    fun rotateDevice(
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
                throw IllegalStateException(parseError(responseBody, responseCode))
            }

            parseRotation(responseBody)
        } finally {
            connection.disconnect()
        }
    }

    fun revokeDevice(
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
                throw IllegalStateException(parseError(responseBody, responseCode))
            }
            true
        } finally {
            connection.disconnect()
        }
    }

    fun listServers(): List<RegisteredServer> {
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
                throw IllegalStateException(parseError(responseBody, responseCode))
            }
            val array = JSONArray(responseBody)
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
        require(parsed.scheme == "http" || parsed.scheme == "https") {
            "Control plane URL must use http or https"
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


    private fun parseServer(serverJson: JSONObject): RegisteredServer = RegisteredServer(
        id = serverJson.getString("id"),
        region = serverJson.getString("region"),
        hostname = serverJson.getString("hostname"),
        publicKey = serverJson.getString("public_key"),
        port = serverJson.getInt("port"),
        healthStatus = serverJson.optString("health_status", "unknown").ifBlank { "unknown" },
        peerCount = if (serverJson.has("peer_count") && !serverJson.isNull("peer_count")) serverJson.getInt("peer_count") else null,
        peerCapacity = if (serverJson.has("peer_capacity") && !serverJson.isNull("peer_capacity")) serverJson.getInt("peer_capacity") else null,
        capacityRemaining = if (serverJson.has("capacity_remaining") && !serverJson.isNull("capacity_remaining")) serverJson.getInt("capacity_remaining") else null,
    )

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
        return RegistrationResult(
            deviceId = json.getString("device_id"),
            clientAddress = json.getString("client_address"),
            provisioned = json.getBoolean("provisioned"),
            server = parseServer(serverJson),
            deviceToken = json.optString("device_token").ifBlank { null },
        )
    }
}
