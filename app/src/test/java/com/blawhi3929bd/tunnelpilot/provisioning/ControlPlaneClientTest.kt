package com.blawhi3929bd.tunnelpilot.provisioning

import com.sun.net.httpserver.HttpServer
import com.blawhi3929bd.tunnelpilot.debug.DebugCliProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.net.InetSocketAddress

class ControlPlaneClientTest {

    private lateinit var server: HttpServer
    private var serverPort: Int = 0

    @Before
    fun setUp() {
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        serverPort = server.address.port
        server.start()
    }

    @After
    fun tearDown() {
        server.stop(0)
    }

    @Test
    fun registerDevice_success() {
        var receivedTokenHeader: String? = null
        var receivedBody: String? = null

        server.createContext("/v1/devices") { exchange ->
            receivedTokenHeader = exchange.requestHeaders.getFirst("X-Device-Token")
            receivedBody = exchange.requestBody.bufferedReader().readText()
            val response = """
                {
                    "status": "accepted",
                    "device_id": "dev-1",
                    "client_address": "10.67.0.2/32",
                    "provisioned": true,
                    "registered_at": "2026-10-23T20:00:00Z",
                    "device_token": "token-123",
                    "server": {
                        "id": "srv-1",
                        "region": "dev",
                        "hostname": "127.0.0.1",
                        "public_key": "srv-pubkey",
                        "port": 51820
                    }
                }
            """.trimIndent()
            val bytes = response.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        val result = client.registerDevice(
            deviceId = "dev-1",
            publicKey = "client-pubkey",
            appVersion = "0.2.0",
            deviceToken = "optional-existing-token",
        )

        assertEquals("dev-1", result.deviceId)
        assertEquals("10.67.0.2/32", result.clientAddress)
        assertTrue(result.provisioned)
        assertEquals("token-123", result.deviceToken)
        assertEquals("srv-1", result.server.id)
        assertEquals("optional-existing-token", receivedTokenHeader)
        assertTrue(receivedBody!!.contains("client-pubkey"))
    }

    @Test
    fun registerDevice_nullDeviceTokenOnRepeatProvisionReturnsNullNotLiteralNullString() {
        server.createContext("/v1/devices") { exchange ->
            val response = """
                {
                    "status": "accepted",
                    "device_id": "dev-1",
                    "client_address": "10.67.0.2/32",
                    "provisioned": true,
                    "registered_at": "2026-10-23T20:00:00Z",
                    "device_token": null,
                    "server": {
                        "id": "srv-1",
                        "region": "dev",
                        "hostname": "127.0.0.1",
                        "public_key": "srv-pubkey",
                        "port": 51820
                    }
                }
            """.trimIndent()
            val bytes = response.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        val result = client.registerDevice(
            deviceId = "dev-1",
            publicKey = "client-pubkey",
            appVersion = "0.2.0",
            deviceToken = "existing-valid-token",
        )

        org.junit.Assert.assertNull(result.deviceToken)
    }

    @Test
    fun rotateDevice_success() {
        var receivedTokenHeader: String? = null
        var receivedBody: String? = null

        server.createContext("/v1/devices/dev-1/rotate") { exchange ->
            receivedTokenHeader = exchange.requestHeaders.getFirst("X-Device-Token")
            receivedBody = exchange.requestBody.bufferedReader().readText()
            val response = """
                {
                    "status": "rotated",
                    "device_id": "dev-1",
                    "client_address": "10.67.0.2/32",
                    "provisioned": true,
                    "server": {
                        "id": "srv-1",
                        "region": "dev",
                        "hostname": "127.0.0.1",
                        "public_key": "srv-pubkey",
                        "port": 51820
                    }
                }
            """.trimIndent()
            val bytes = response.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        val result = client.rotateDevice(
            deviceId = "dev-1",
            publicKey = "new-pubkey",
            appVersion = "0.2.0",
            deviceToken = "secret-token",
        )

        assertEquals("rotated", result.status)
        assertEquals("dev-1", result.deviceId)
        assertEquals("10.67.0.2/32", result.clientAddress)
        assertTrue(result.provisioned)
        assertEquals("secret-token", receivedTokenHeader)
        assertTrue(receivedBody!!.contains("new-pubkey"))
    }

    @Test(expected = IllegalStateException::class)
    fun rotateDevice_serverErrorThrows() {
        server.createContext("/v1/devices/dev-1/rotate") { exchange ->
            val error = """{"detail": "Invalid device token"}"""
            val bytes = error.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(401, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        client.rotateDevice(
            deviceId = "dev-1",
            publicKey = "new-pubkey",
            appVersion = "0.2.0",
            deviceToken = "bad-token",
        )
    }

    @Test
    fun revokeDevice_success() {
        var receivedTokenHeader: String? = null
        server.createContext("/v1/devices/dev-1") { exchange ->
            receivedTokenHeader = exchange.requestHeaders.getFirst("X-Device-Token")
            val response = """{"status": "revoked", "device_id": "dev-1"}"""
            val bytes = response.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        val success = client.revokeDevice("dev-1", "my-token")
        assertTrue(success)
        assertEquals("my-token", receivedTokenHeader)
    }

    @Test(expected = IllegalStateException::class)
    fun revokeDevice_serverErrorThrows() {
        server.createContext("/v1/devices/dev-1") { exchange ->
            val error = """{"detail": "Gateway peer removal failed"}"""
            val bytes = error.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(502, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        client.revokeDevice("dev-1", "my-token")
    }

    @Test
    fun listServers_parsesHealthAndCapacity() {
        server.createContext("/v1/servers") { exchange ->
            val response = """
                [
                    {
                        "id": "dev-1",
                        "region": "dev",
                        "hostname": "10.33.209.129",
                        "public_key": "srv-pubkey",
                        "port": 51820,
                        "enabled": true,
                        "health_status": "ok",
                        "peer_count": 2,
                        "peer_capacity": 240,
                        "capacity_remaining": 238
                    }
                ]
            """.trimIndent()
            val bytes = response.toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        val servers = client.listServers()
        assertEquals(1, servers.size)
        assertEquals("dev-1", servers[0].id)
        assertEquals("ok", servers[0].healthStatus)
        assertEquals(2, servers[0].peerCount)
        assertEquals(240, servers[0].peerCapacity)
        assertEquals(238, servers[0].capacityRemaining)
    }

    @Test
    fun listServers_emptyCatalogReturnsEmptyList() {
        server.createContext("/v1/servers") { exchange ->
            val bytes = "[]".toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        assertTrue(client.listServers().isEmpty())
    }

    @Test(expected = IllegalStateException::class)
    fun listServers_malformedJsonThrows() {
        server.createContext("/v1/servers") { exchange ->
            val bytes = "{not-an-array}".toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        client.listServers()
    }

    @Test
    fun registerDevice_conflictCarriesHttp409StatusCode() {
        server.createContext("/v1/devices") { exchange ->
            val bytes = """{"detail": "device_id is already registered with a different public key"}"""
                .toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(409, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }

        val client = ControlPlaneClient("http://127.0.0.1:$serverPort")
        try {
            client.registerDevice("dev-1", "pubkey", "0.2.0", "token")
            fail("Expected ControlPlaneHttpException")
        } catch (e: ControlPlaneHttpException) {
            assertEquals(409, e.statusCode)
            assertTrue(e.message!!.contains("different public key"))
        }
    }

    @Test
    fun debugCliProvider_isAllowedCallerUidEnforcesShellRootAndDebugBuild() {
        assertTrue(DebugCliProvider.isAllowedCallerUid(uid = 2000, appUid = 10234, isDebugBuild = true))
        assertTrue(DebugCliProvider.isAllowedCallerUid(uid = 0, appUid = 10234, isDebugBuild = true))
        assertTrue(DebugCliProvider.isAllowedCallerUid(uid = 10234, appUid = 10234, isDebugBuild = true))
        assertFalse(DebugCliProvider.isAllowedCallerUid(uid = 10999, appUid = 10234, isDebugBuild = true))
        assertFalse(DebugCliProvider.isAllowedCallerUid(uid = 2000, appUid = 10234, isDebugBuild = false))
    }

    private fun resolveAppFile(relativeToApp: String): java.io.File {
        val direct = java.io.File(relativeToApp)
        if (direct.exists()) return direct
        val fromRoot = java.io.File("app/$relativeToApp")
        if (fromRoot.exists()) return fromRoot
        return direct
    }

    @Test
    fun sourceManifests_enforceDebugOnlyCliProviderAndCleartextTraffic() {
        val mainManifest = resolveAppFile("src/main/AndroidManifest.xml")
        assertTrue(
            "Main AndroidManifest.xml must exist at ${mainManifest.absolutePath}",
            mainManifest.exists(),
        )
        val mainContent = mainManifest.readText()
        assertFalse(mainContent.contains("DebugCliProvider"))
        assertFalse(mainContent.contains("usesCleartextTraffic"))

        val debugManifest = resolveAppFile("src/debug/AndroidManifest.xml")
        assertTrue(
            "Debug AndroidManifest.xml must exist at ${debugManifest.absolutePath}",
            debugManifest.exists(),
        )
        val debugContent = debugManifest.readText()
        assertTrue(debugContent.contains("DebugCliProvider"))
        assertTrue(debugContent.contains("usesCleartextTraffic=\"true\""))
    }

    @Test
    fun mergedReleaseManifest_excludesDebugCliProviderAndCleartextTraffic() {
        val mergedReleaseManifest = resolveAppFile(
            "build/intermediates/merged_manifest/release/processReleaseMainManifest/AndroidManifest.xml",
        )
        assertTrue(
            "Merged release manifest artifact is missing at ${mergedReleaseManifest.absolutePath}; " +
                "ensure :app:processReleaseMainManifest runs before unit tests",
            mergedReleaseManifest.exists(),
        )
        val releaseContent = mergedReleaseManifest.readText()
        assertTrue(releaseContent.contains("com.blawhi3929bd.tunnelpilot.MainActivity"))
        assertFalse(releaseContent.contains("DebugCliProvider"))
        assertFalse(releaseContent.contains("usesCleartextTraffic"))
    }

    @Test
    fun releaseCleartextPolicy_rejectsNonLoopbackHttpAndAllowsLoopback() {
        val remoteHttpClient = ControlPlaneClient("http://203.0.113.10:8000", allowCleartext = false)
        try {
            remoteHttpClient.listServers()
            fail("Expected IllegalArgumentException for remote http:// URL when allowCleartext=false")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("HTTPS is required"))
        }

        server.createContext("/v1/servers") { exchange ->
            val bytes = "[]".toByteArray(Charsets.UTF_8)
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.write(bytes)
            exchange.close()
        }
        val loopbackClient = ControlPlaneClient("http://127.0.0.1:$serverPort", allowCleartext = false)
        assertTrue(loopbackClient.listServers().isEmpty())
    }
}
