pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "TunnelPilot"
include(":app")

include(":wireguard-tunnel")
project(":wireguard-tunnel").projectDir = file("third_party/wireguard-tunnel")
