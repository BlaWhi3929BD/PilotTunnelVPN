package com.wireguard.crypto

import java.security.SecureRandom

/**
 * Generates a WireGuard-compatible Curve25519 keypair using the bundled
 * WireGuard crypto primitives. Private key material never leaves this class
 * except through the returned Key object.
 */
object TunnelPilotKeyGenerator {
    private const val KEY_SIZE = 32

    fun generatePrivateKey(): Key {
        val bytes = ByteArray(KEY_SIZE)
        SecureRandom().nextBytes(bytes)

        // WireGuard/X25519 private-key clamping.
        bytes[0] = (bytes[0].toInt() and 248).toByte()
        bytes[31] = (bytes[31].toInt() and 127 or 64).toByte()

        return Key.fromBytes(bytes)
    }

    fun generatePublicKey(privateKey: Key): Key {
        val publicKey = ByteArray(KEY_SIZE)
        Curve25519.eval(publicKey, 0, privateKey.getBytes(), null)
        return Key.fromBytes(publicKey)
    }
}
