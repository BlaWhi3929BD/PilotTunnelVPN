package com.blawhi3929bd.tunnelpilot.provisioning

object WireGuardConfigFactory {
    fun create(
        privateKey: String,
        clientAddress: String,
        server: RegisteredServer,
    ): String {
        require(privateKey.isNotBlank()) { "Client private key is required" }
        require(clientAddress.isNotBlank()) { "Client address is required" }
        require(server.hostname.isNotBlank()) { "Gateway hostname is required" }
        require(server.publicKey.isNotBlank()) { "Gateway public key is required" }
        require(server.port in 1..65535) { "Gateway port is invalid" }

        val endpointHost = if (server.hostname.contains(":") && !server.hostname.startsWith("[")) {
            "[${server.hostname}]"
        } else {
            server.hostname
        }

        return buildString {
            appendLine("[Interface]")
            appendLine("PrivateKey = $privateKey")
            appendLine("Address = $clientAddress")
            appendLine("DNS = 1.1.1.1")
            appendLine()
            appendLine("[Peer]")
            appendLine("PublicKey = ${server.publicKey}")
            appendLine("AllowedIPs = 0.0.0.0/0")
            appendLine("Endpoint = $endpointHost:${server.port}")
            appendLine("PersistentKeepalive = 25")
        }
    }
}
