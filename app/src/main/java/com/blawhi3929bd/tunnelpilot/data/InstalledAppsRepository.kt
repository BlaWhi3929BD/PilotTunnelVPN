package com.blawhi3929bd.tunnelpilot.data

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager

class InstalledAppsRepository(
    context: Context,
    private val ownPackageName: String = context.packageName,
) {
    private val packageManager = context.packageManager

    fun getLaunchableApps(): List<InstalledApp> {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return packageManager
            .queryIntentActivities(intent, PackageManager.MATCH_ALL)
            .asSequence()
            .map { info ->
                InstalledApp(
                    packageName = info.activityInfo.packageName,
                    label = info.loadLabel(packageManager).toString(),
                )
            }
            .filterNot { it.packageName == ownPackageName }
            .distinctBy { it.packageName }
            .sortedBy { it.label.lowercase() }
            .toList()
    }
}
