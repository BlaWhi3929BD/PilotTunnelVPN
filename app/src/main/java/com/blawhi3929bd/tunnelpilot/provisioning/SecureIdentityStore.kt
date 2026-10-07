package com.blawhi3929bd.tunnelpilot.provisioning

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Stores the device identity and control-plane credential encrypted with Android Keystore. */
class SecureIdentityStore(context: Context) {
    private val prefs = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun getOrCreateDeviceId(): String {
        prefs.getString(KEY_DEVICE_ID, null)?.let { return it }
        val deviceId = UUID.randomUUID().toString()
        prefs.edit { putString(KEY_DEVICE_ID, deviceId) }
        return deviceId
    }

    fun loadPrivateKey(): String? = loadEncrypted(KEY_PRIVATE_KEY_CIPHERTEXT, KEY_PRIVATE_KEY_IV)

    fun savePrivateKey(privateKey: String) = saveEncrypted(KEY_PRIVATE_KEY_CIPHERTEXT, KEY_PRIVATE_KEY_IV, privateKey)

    fun clearPrivateKey() {
        prefs.edit {
            remove(KEY_PRIVATE_KEY_CIPHERTEXT)
            remove(KEY_PRIVATE_KEY_IV)
        }
    }

    fun loadDeviceToken(): String? = loadEncrypted(KEY_DEVICE_TOKEN_CIPHERTEXT, KEY_DEVICE_TOKEN_IV)

    fun saveDeviceToken(token: String) = saveEncrypted(KEY_DEVICE_TOKEN_CIPHERTEXT, KEY_DEVICE_TOKEN_IV, token)

    fun clearDeviceToken() {
        prefs.edit {
            remove(KEY_DEVICE_TOKEN_CIPHERTEXT)
            remove(KEY_DEVICE_TOKEN_IV)
        }
    }

    private fun saveEncrypted(ciphertextKey: String, ivKey: String, value: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ciphertext = cipher.doFinal(value.toByteArray(StandardCharsets.UTF_8))
        prefs.edit {
            putString(ciphertextKey, Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            putString(ivKey, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
        }
    }

    private fun loadEncrypted(ciphertextKey: String, ivKey: String): String? {
        val ciphertext = prefs.getString(ciphertextKey, null) ?: return null
        val iv = prefs.getString(ivKey, null) ?: return null
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP))
                .toString(StandardCharsets.UTF_8)
        }.getOrElse {
            prefs.edit {
                remove(ciphertextKey)
                remove(ivKey)
            }
            null
        }
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        if (!keyStore.containsAlias(ALIAS)) {
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
            generator.init(
                KeyGenParameterSpec.Builder(
                    ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setUserAuthenticationRequired(false)
                    .build(),
            )
            generator.generateKey()
        }
        return (keyStore.getEntry(ALIAS, null) as KeyStore.SecretKeyEntry).secretKey
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val NAME = "tunnelpilot_identity"
        const val ALIAS = "tunnelpilot_identity_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_PRIVATE_KEY_CIPHERTEXT = "private_key_ciphertext"
        const val KEY_PRIVATE_KEY_IV = "private_key_iv"
        const val KEY_DEVICE_TOKEN_CIPHERTEXT = "device_token_ciphertext"
        const val KEY_DEVICE_TOKEN_IV = "device_token_iv"
    }
}
