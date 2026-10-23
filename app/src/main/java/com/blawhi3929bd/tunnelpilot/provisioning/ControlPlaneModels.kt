package com.blawhi3929bd.tunnelpilot.provisioning

data class RegisteredServer(
    val id: String,
    val region: String,
    val hostname: String,
    val publicKey: String,
    val port: Int,
)

data class RotationResult(
    val status: String,
    val deviceId: String,
    val clientAddress: String,
    val provisioned: Boolean,
    val server: RegisteredServer,
)

data class RegistrationResult(
    val deviceId: String,
    val clientAddress: String,
    val provisioned: Boolean,
    val server: RegisteredServer,
    val deviceToken: String?,
)
