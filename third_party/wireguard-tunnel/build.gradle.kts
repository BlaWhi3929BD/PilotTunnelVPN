@file:Suppress("UnstableApiUsage")

plugins {
    id("com.android.library")
}

android {
    namespace = "com.blawhi3929bd.tunnelpilot.tunnel"
    compileSdk = 37

    defaultConfig {
        minSdk = 24
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    externalNativeBuild {
        cmake {
            path("tools/CMakeLists.txt")
        }
    }

    buildTypes {
        all {
            externalNativeBuild {
                cmake {
                    targets("libwg-go.so", "libwg.so", "libwg-quick.so")
                    arguments("-DGRADLE_USER_HOME=${project.gradle.gradleUserHomeDir}")
                    arguments("-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON")
                }
            }
        }

        release {
            externalNativeBuild {
                cmake {
                    arguments("-DANDROID_PACKAGE_NAME=com.blawhi3929bd.tunnelpilot")
                }
            }
        }

        debug {
            externalNativeBuild {
                cmake {
                    arguments("-DANDROID_PACKAGE_NAME=com.blawhi3929bd.tunnelpilot.debug")
                }
            }
        }
    }

    lint {
        disable += "LongLogTag"
        disable += "NewApi"
    }
}

dependencies {
    implementation("androidx.annotation:annotation:1.9.1")
    implementation("androidx.collection:collection:1.6.0")
    compileOnly("com.google.code.findbugs:jsr305:3.0.2")
}
