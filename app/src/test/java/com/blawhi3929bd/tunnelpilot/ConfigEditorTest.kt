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
            ExcludedApplications = another.package

            [Peer]
            PublicKey = server
            AllowedIPs = 0.0.0.0/0
        """.trimIndent()

        val edited = ConfigEditor.withIncludedApplications(
            config,
            setOf("com.example.alpha", "com.example.beta"),
        )

        assertFalse(edited.contains("old.package"))
        assertFalse(edited.contains("another.package"))
        assertTrue(edited.contains("IncludedApplications = com.example.alpha"))
        assertTrue(edited.contains("IncludedApplications = com.example.beta"))
    }

    @Test
    fun empty_allow_list_removes_previous_filters() {
        val edited = ConfigEditor.withIncludedApplications(
            """
            [Interface]
            PrivateKey = test
            IncludedApplications = old.package

            [Peer]
            PublicKey = server
            AllowedIPs = 0.0.0.0/0
            """.trimIndent(),
            emptySet(),
        )

        assertFalse(edited.contains("IncludedApplications"))
        assertFalse(edited.contains("ExcludedApplications"))
    }
}
