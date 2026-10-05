package com.blawhi3929bd.tunnelpilot

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigEditorTest {
    @Test
    fun replaces_existing_application_filters() {
        val config = """
            [Interface]
            PrivateKey = test
            Address = 10.0.0.2/32
            IncludedApplications = old.package

            [Peer]
            PublicKey = server
            AllowedIPs = 0.0.0.0/0
        """.trimIndent()

        val edited = ConfigEditor.withIncludedApplications(
            config,
            setOf("com.example.alpha", "com.example.beta"),
        )

        assertFalse(edited.contains("old.package"))
        assertTrue(edited.contains("IncludedApplications = com.example.alpha"))
        assertTrue(edited.contains("IncludedApplications = com.example.beta"))
    }
}
