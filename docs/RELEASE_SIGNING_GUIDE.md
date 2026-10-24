# TunnelPilot — Release Signing & Production Build Guide

This guide describes how to securely generate and configure official production signing credentials for TunnelPilot without exposing private keys or committing credentials to Git.

---

## 1. Safety Rules for Release Signing

> [!CAUTION]
> **Never commit your `.jks` keystore or `keystore.properties` to Git.**
> - Keep multiple secure backups of your release keystore and passwords (e.g., in a password manager).
> - If you lose your upload key and haven't enrolled in Google Play App Signing, you will not be able to update your application in Google Play!

---

## 2. Step 1: Generate your Private Release Keystore

Run the following command on your local computer using `keytool` (which comes with JDK 17):

```bash
keytool -genkeypair -v \
  -keystore tunnelpilot-release.jks \
  -alias tunnelpilot \
  -keyalg RSA \
  -keysize 4096 \
  -validity 10000 \
  -deststoretype PKCS12
```

You will be prompted for:
1. **Keystore password:** Choose a strong, unique passphrase.
2. **Key details:** Enter your name / organization.
3. **Key password:** Press Enter to reuse the keystore password.

This will generate a file named `tunnelpilot-release.jks`. Store it in a secure location outside the repository (for example, `~/.android/keys/tunnelpilot-release.jks`).

---

## 3. Step 2: Configure `keystore.properties`

In the root of the `PilotTunnelVPN` repository, copy the example template:

```bash
cp keystore.properties.example keystore.properties
chmod 600 keystore.properties
```

Edit `keystore.properties` with your private details:

```properties
storeFile=/home/username/.android/keys/tunnelpilot-release.jks
storePassword=YourStrongKeystorePassword
keyAlias=tunnelpilot
keyPassword=YourStrongKeystorePassword
```

*(Note: `keystore.properties` is already listed in `.gitignore` and will never be tracked by Git).*

---

## 4. Step 3: Build the Production Signed Artifacts

When `keystore.properties` is present, Gradle automatically signs the release artifacts:

```bash
# Build the official Android App Bundle (.aab) for Google Play:
./gradlew :app:bundleRelease

# (Optional) Build a standalone signed Release APK (.apk):
./gradlew :app:assembleRelease
```

### Output Locations:
- **Play Store App Bundle:** `app/build/outputs/bundle/release/app-release.aab`
- **Release APK:** `app/build/outputs/apk/release/app-release.apk`

---

## 5. Step 4: Verify the Signature

Verify that the artifact is signed correctly with your key:

```bash
# Verify using jarsigner or apksigner:
jarsigner -verify -verbose -certs app/build/outputs/bundle/release/app-release.aab
```

If the output displays `jar verified`, the artifact is properly signed and ready for upload to the **Internal Testing** or **Production** track in Google Play Console!
