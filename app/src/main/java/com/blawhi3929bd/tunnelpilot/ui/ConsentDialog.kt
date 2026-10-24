package com.blawhi3929bd.tunnelpilot.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * GDPR / Privacy consent prompt displayed before presenting advertising.
 * Fully transparent: discloses that VPN network traffic is NEVER tracked or monetized,
 * and that ads are strictly confined to the in-app user interface.
 */
@Composable
fun ConsentDialog(
    onConsentChoice: (Boolean) -> Unit,
    onOpenPrivacyPolicy: () -> Unit = {},
) {
    AlertDialog(
        onDismissRequest = { /* user must make a choice */ },
        title = {
            Text(
                text = "Privacy & Advertising Choice",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
        },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "TunnelPilot is free and open-source. To keep our high-speed WireGuard servers online for everyone, the app displays non-intrusive sponsor banners inside the app.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(modifier = Modifier.height(10.dp))
                Text(
                    text = "🔒 Zero-Log Data Protection: Your VPN tunnel traffic, visited websites, and DNS queries are strictly encrypted and NEVER tracked, inspected, or shared with advertisers.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(modifier = Modifier.height(10.dp))
                Text(
                    text = "You can choose personalized ads for more relevant recommendations, or basic non-personalized ads.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(modifier = Modifier.height(6.dp))
                TextButton(
                    onClick = onOpenPrivacyPolicy,
                    modifier = Modifier.padding(0.dp),
                ) {
                    Text(
                        text = "Read Privacy Policy & Zero-Log Declaration",
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConsentChoice(true) },
            ) {
                Text("Accept Personalized")
            }
        },
        dismissButton = {
            OutlinedButton(
                onClick = { onConsentChoice(false) },
            ) {
                Text("Basic Ads Only")
            }
        },
    )
}
