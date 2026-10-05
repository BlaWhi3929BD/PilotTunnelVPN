package com.blawhi3929bd.tunnelpilot.provisioning

sealed interface ProvisioningState {
    data object NotConfigured : ProvisioningState
    data object Provisioning : ProvisioningState
    data class Provisioned(
        val deviceId: String,
        val clientAddress: String,
    ) : ProvisioningState
    data class Error(val message: String) : ProvisioningState
}
