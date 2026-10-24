package com.blawhi3929bd.tunnelpilot.provisioning

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class WireGuardConfigFactoryTest {

    private val sampleServer = RegisteredServer(
        id = "srv-frankfurt-1",
        region = "eu-central",
        hostname = "vpn.example.com",
        publicKey = "bm90YXJlYWxrZXkxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMzQ=",
        port = 51820,
    )

    @Test
    fun create_validInputs_producesExpectedWireGuardConfig() {
        val config = WireGuardConfigFactory.create(
            privateKey = "Y2xpZW50cHJpdmF0ZWtleTEyMzQ1Njc4OTAxMjM0NTY=",
            clientAddress = "10.67.0.2/32",
            server = sampleServer,
        )

        assertTrue(config.contains("[Interface]"))
        assertTrue(config.contains("PrivateKey = Y2xpZW50cHJpdmF0ZWtleTEyMzQ1Njc4OTAxMjM0NTY="))
        assertTrue(config.contains("Address = 10.67.0.2/32"))
        assertTrue(config.contains("DNS = 1.1.1.1, 8.8.8.8"))
        assertTrue(config.contains("[Peer]"))
        assertTrue(config.contains("PublicKey = bm90YXJlYWxrZXkxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMzQ="))
        assertTrue(config.contains("AllowedIPs = 0.0.0.0/0"))
        assertTrue(config.contains("Endpoint = vpn.example.com:51820"))
        assertTrue(config.contains("PersistentKeepalive = 25"))
    }

    @Test
    fun create_ipv6Hostname_wrapsInBrackets() {
        val ipv6Server = sampleServer.copy(hostname = "2001:db8::1")
        val config = WireGuardConfigFactory.create(
            privateKey = "privkey",
            clientAddress = "10.67.0.5/32",
            server = ipv6Server,
        )

        assertTrue(config.contains("Endpoint = [2001:db8::1]:51820"))
    }

    @Test
    fun create_alreadyBracketedIpv6Hostname_preservesBrackets() {
        val ipv6Server = sampleServer.copy(hostname = "[2001:db8::1]")
        val config = WireGuardConfigFactory.create(
            privateKey = "privkey",
            clientAddress = "10.67.0.5/32",
            server = ipv6Server,
        )

        assertTrue(config.contains("Endpoint = [2001:db8::1]:51820"))
    }

    @Test
    fun create_blankPrivateKey_throwsIllegalArgumentException() {
        try {
            WireGuardConfigFactory.create(
                privateKey = "   ",
                clientAddress = "10.67.0.2/32",
                server = sampleServer,
            )
            fail("Expected IllegalArgumentException for blank private key")
        } catch (e: IllegalArgumentException) {
            assertEquals("Client private key is required", e.message)
        }
    }

    @Test
    fun create_blankClientAddress_throwsIllegalArgumentException() {
        try {
            WireGuardConfigFactory.create(
                privateKey = "privkey",
                clientAddress = "",
                server = sampleServer,
            )
            fail("Expected IllegalArgumentException for blank client address")
        } catch (e: IllegalArgumentException) {
            assertEquals("Client address is required", e.message)
        }
    }

    @Test
    fun create_invalidPort_throwsIllegalArgumentException() {
        try {
            WireGuardConfigFactory.create(
                privateKey = "privkey",
                clientAddress = "10.67.0.2/32",
                server = sampleServer.copy(port = 70000),
            )
            fail("Expected IllegalArgumentException for invalid port")
        } catch (e: IllegalArgumentException) {
            assertEquals("Gateway port is invalid", e.message)
        }
    }
}
