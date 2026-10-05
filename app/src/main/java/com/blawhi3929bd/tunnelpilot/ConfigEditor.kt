package com.blawhi3929bd.tunnelpilot

/** Applies Android-specific per-app routing directives to a WireGuard config. */
object ConfigEditor {
    private val appDirective = Regex("^\\s*(IncludedApplications|ExcludedApplications)\\s*=.*$", RegexOption.IGNORE_CASE)

    fun withIncludedApplications(config: String, packageNames: Set<String>): String {
        val cleaned = config
            .lineSequence()
            .filterNot { appDirective.matches(it) }
            .toMutableList()

        if (packageNames.isEmpty()) return cleaned.joinToString("\n").trimEnd() + "\n"

        val interfaceHeader = cleaned.indexOfFirst { it.trim().equals("[Interface]", ignoreCase = true) }
        require(interfaceHeader >= 0) { "WireGuard config is missing [Interface]" }

        var insertAt = interfaceHeader + 1
        while (insertAt < cleaned.size) {
            val line = cleaned[insertAt].trim()
            if (line.startsWith("[")) break
            if (line.isEmpty()) {
                insertAt++
                continue
            }
            insertAt++
        }

        val directives = packageNames
            .asSequence()
            .filter { it.isNotBlank() }
            .distinct()
            .sorted()
            .map { "IncludedApplications = $it" }
            .toList()

        cleaned.addAll(insertAt, directives)
        return cleaned.joinToString("\n").trimEnd() + "\n"
    }
}
