package com.blawhi3929bd.tunnelpilot.provisioning

data class RegisteredServer(
    val id: String,
    val region: String,
    val hostname: String,
    val publicKey: String,
    val port: Int,
    val healthStatus: String = "unknown",
    val peerCount: Int? = null,
    val peerCapacity: Int? = null,
    val capacityRemaining: Int? = null,
    val tier: String = "free",
)

data class RotationResult(
    val status: String,
    val deviceId: String,
    val clientAddress: String,
    val provisioned: Boolean,
    val server: RegisteredServer,
    val tier: String = "free",
)

data class RegistrationResult(
    val deviceId: String,
    val clientAddress: String,
    val provisioned: Boolean,
    val server: RegisteredServer,
    val deviceToken: String?,
    val tier: String = "free",
)

data class MigrationResult(
    val status: String,
    val deviceId: String,
    val previousServerId: String,
    val clientAddress: String,
    val provisioned: Boolean,
    val server: RegisteredServer,
    val tier: String = "free",
)

data class TierUpdateResult(
    val status: String,
    val deviceId: String,
    val tier: String,
)
