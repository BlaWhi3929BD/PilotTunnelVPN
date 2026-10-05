package com.blawhi3929bd.tunnelpilot.provisioning

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
    fun registerDevice(deviceId: String, publicKey: String, appVersion: String): RegistrationResult {
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

    private fun parseRegistration(body: String): RegistrationResult {
        val json = JSONObject(body)
        val serverJson = json.getJSONObject("server")
        return RegistrationResult(
            deviceId = json.getString("device_id"),
            clientAddress = json.getString("client_address"),
            provisioned = json.getBoolean("provisioned"),
            server = RegisteredServer(
                id = serverJson.getString("id"),
                region = serverJson.getString("region"),
                hostname = serverJson.getString("hostname"),
                publicKey = serverJson.getString("public_key"),
                port = serverJson.getInt("port"),
            ),
        )
    }
}
