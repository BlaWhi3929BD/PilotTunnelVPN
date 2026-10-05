package com.blawhi3929bd.tunnelpilot

/**
 * Applies Android-only application routing directives to a wg-quick config.
 *
 * IncludedApplications and ExcludedApplications are mutually exclusive in the
 * WireGuard Android format. We always remove both before adding the requested
 * allow-list, which gives Auto-VPN deterministic behavior.
 */
object ConfigEditor {
    private val appDirective = Regex("^\\s*(IncludedApplications|ExcludedApplications)\\s*=.*$", RegexOption.IGNORE_CASE)

    fun withIncludedApplications(config: String, packageNames: Set<String>): String {
        val cleaned = config
            .lineSequence()
            .filterNot { appDirective.matches(it) }
            .toList()
            .toMutableList()

        if (packageNames.isEmpty()) {
            return cleaned.joinToString("\n").trimEnd() + "\n"
        }

        val interfaceHeader = cleaned.indexOfFirst { it.trim().equals("[Interface]", ignoreCase = true) }
        require(interfaceHeader >= 0) { "WireGuard config is missing [Interface]" }

        var insertAt = interfaceHeader + 1
        while (insertAt < cleaned.size && cleaned[insertAt].trim().isNotEmpty() && !cleaned[insertAt].trim().startsWith("[")) {
            insertAt++
        }

        val directives = packageNames
            .toList()
            .sorted()
            .map { "IncludedApplications = $it" }

        cleaned.addAll(insertAt, directives)
        return cleaned.joinToString("\n").trimEnd() + "\n"
    }
}
