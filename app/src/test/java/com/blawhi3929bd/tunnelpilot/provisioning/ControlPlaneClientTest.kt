package com.blawhi3929bd.tunnelpilot.provisioning

import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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
}
