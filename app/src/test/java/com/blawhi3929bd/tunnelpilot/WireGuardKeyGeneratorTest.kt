package com.blawhi3929bd.tunnelpilot

import com.wireguard.crypto.Key
import com.wireguard.crypto.TunnelPilotKeyGenerator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class WireGuardKeyGeneratorTest {
    @Test
    fun generatesValidWireGuardKeyPair() {
        val privateKey = TunnelPilotKeyGenerator.generatePrivateKey()
        val publicKey = TunnelPilotKeyGenerator.generatePublicKey(privateKey)

        assertEquals(Key.Format.BASE64.getLength(), privateKey.toBase64().length)
        assertEquals(Key.Format.BASE64.getLength(), publicKey.toBase64().length)
        assertNotEquals(privateKey, publicKey)
        assertEquals(privateKey, Key.fromBase64(privateKey.toBase64()))
        assertEquals(publicKey, Key.fromBase64(publicKey.toBase64()))
    }
}
