# TunnelPilot — полный handoff для coding agent

**Документ обновлён:** 2026-10-23  
**Репозиторий:** https://github.com/BlaWhi3929BD/PilotTunnelVPN  
**Последний подтверждённый GitHub `main`:** `9afa03a077cde93c57176ffeca537f76f228b668` — `feat: persist and authenticate device state` (2026-10-07).  
**Язык владельца проекта:** русский. Общаться с ним по-русски; названия кода/API/коммитов можно оставлять английскими.  
**Назначение документа:** передать новому coding agent (Codex, OpenCode, Claude Code, Antigravity CLI или похожему) контекст проекта, фактическое состояние, принятые решения, известные риски и следующие задачи без необходимости восстанавливать длинную предыдущую переписку.

> Важно: GitHub был проверен 2026-10-23. Последний подтверждённый commit — `9afa03a…`. Пакет M2.3b для ротации ключей ранее был подготовлен как ZIP, но в переписке нет подтверждения, что он был применён, протестирован и запушен. **Не считай M2.3b частью GitHub HEAD, пока не проверишь дерево репозитория и `git status`.** В реальной локальной копии может быть другой/более новый незакоммиченный код — сначала проверь его.

---

## 0. Инструкции агенту: как начинать работу

Ты — основной инженер проекта TunnelPilot. Не пересоздавай проект и не переписывай архитектуру без веской причины. Сохраняй работающий end-to-end путь, улучшай его итеративно и подтверждай изменения тестами.

### Первые команды

Сначала выполни и проанализируй:

```bash
git status --short
git branch --show-current
git log -8 --oneline --decorate
git rev-parse HEAD
git remote -v
```

Если есть незакоммиченные изменения — **не стирай, не делай `git reset --hard`, не переключай ветку и не перезаписывай файлы вслепую**. Сначала изучи diff:

```bash
git diff --stat
git diff
```

Проверь, совпадает ли `HEAD` с последним GitHub `main`. Не полагайся только на этот документ: исходный код репозитория и тесты — источник истины. Этот handoff описывает известное состояние на момент подготовки.

### Правила работы

1. Сделай небольшую архитектурно цельную порцию изменений, не огромный rewrite.
2. Перед изменением изучи связанные реализации, тесты, README и вызовы API.
3. Не выдумывай API библиотек. Для актуальных Android/Gradle/Compose/FastAPI API используй официальные docs и Context7.
4. Для каждого исправления добавляй тесты: серверные unit/API-тесты и Android unit tests, где применимо.
5. В конце запусти проверки, которые доступны в реальном workspace, и укажи точный результат. Никогда не говори, что тесты прошли, если их не запускал.
6. Не запускай команды, способные удалить пользовательские данные, WireGuard-конфиги или ключи, без явной необходимости и объяснения.
7. Не запускай control plane или gateway agent наружу на Internet для удобства теста. Не ослабляй auth/TLS/security boundary ради теста.
8. Не коммить secrets, WireGuard private keys, device tokens, gateway-agent tokens, `.env`, SQLite DB, signing keys или APK credentials.
9. Не используй `git add .` автоматически. Стаджи только ожидаемые файлы после `git status --short`.
10. Не коммить и не пушь от имени владельца, если он явно не разрешил это в текущей задаче. Если у GitHub MCP недостаточно прав, используй локальную авторизацию Git/`gh` или предоставь готовый diff/bundle — не притворяйся, что push состоялся.
11. По умолчанию избегай дополнительных вопросов, если можно безопасно двигаться на основе репозитория и описанных требований. Если без решения пользователя нельзя выбрать безопасный вариант, задай один конкретный вопрос.
12. Фиксируй архитектурные решения в `docs/` и обновляй инструкции после существенных изменений.

### Критически важные первые действия в новом workspace

- Проверь актуальный `main` и наличие локальных изменений.
- Убедись, что M2.3a-код (SQLite/device token) действительно присутствует.
- Проверь, присутствует ли endpoint/key-rotation implementation из M2.3b. Если нет — не предполагай, что ранее созданный ZIP находится в новом workspace; изучи код и реализуй ротацию с нуля в рамках текущего Git состояния.
- Запусти Python tests и Gradle проверки до первого изменения, чтобы зафиксировать baseline.
- Проверь `.gitignore`: база в `server/data/*.db` и `*.db-*` должна игнорироваться.

---

## 1. Что такое TunnelPilot

TunnelPilot — проект собственного **Android-first бесплатного WireGuard VPN-клиента** с собственным control plane и собственными gateway agent'ами. Это не просто UI поверх стороннего VPN API. Клиент должен самостоятельно генерировать личный ключ, регистрировать только публичный ключ на backend, получить назначенный VPN IP и параметры сервера, создать WireGuard-конфигурацию локально и подключиться к своему gateway.

### Видение продукта

Долгосрочная идея:

- бесплатный VPN как базовый вариант;
- возможная внутренняя реклама, не связанная с перехватом/подменой VPN-трафика;
- платный/premium вариант без рекламы и с дополнительными возможностями;
- разные VPN-серверы/регионы, выбор по доступности, нагрузке и качеству;
- per-app routing и далее удобный Smart Apps / Smart Auto режим;
- минимальный сбор данных, безопасное хранение identity и прозрачные объяснения пользователю.

Рекламная модель пока **не реализована** и не должна вмешиваться в маршрутизацию пользовательского трафика. Нельзя перенаправлять трафик других приложений ради манипуляции рекламой/монетизации. Любая монетизация — отдельно от data plane VPN, с раскрытием информации, согласием и проверкой применимых политик магазинов.

### Текущая приоритетность

Сейчас приоритет — не UI-монетизация, а надёжность lifecycle устройств и peer'ов:

1. Довести M2.3 lifecycle/security: persistent state, authenticated device identity, peer reconciliation, rotation, revoke и recovery.
2. Продолжить эксплуатационное hardening и диагностику производительности.
3. Довести клиентский UX, connection status/error messages, reconnect и автоматическое восстановление.
4. Затем делать Smart Apps/Smart Auto и выбор серверов.
5. Потом onboarding, privacy/legal documentation, monetization architecture и release preparation.

---

## 2. Подтверждённый статус

### Последний подтверждённый commit

- `9afa03a077cde93c57176ffeca537f76f228b668` — `feat: persist and authenticate device state`.
- Предыдущий cleanup: `542a6a7234c5b30a8e1f9f9c91e7c21ceadef990` — `chore: clean up test artifacts`.
- Предыдущий E2E: `b622fd0d9b8e687b98e7fea3bedd021dd81867af` — `feat: complete end-to-end provisioning`.
- Android lint cleanup: `4af22e4dd85da95a0909119d32608b10a4ef91e4` — `lint fix`.

Ссылки:

- HEAD: https://github.com/BlaWhi3929BD/PilotTunnelVPN/commit/9afa03a077cde93c57176ffeca537f76f228b668
- E2E commit: https://github.com/BlaWhi3929BD/PilotTunnelVPN/commit/b622fd0d9b8e687b98e7fea3bedd021dd81867af
- Репозиторий: https://github.com/BlaWhi3929BD/PilotTunnelVPN

### Подтверждено запуском владельца на реальном Android + Linux gateway

M2.2 E2E прошёл:

- Android сам генерирует WireGuard private key локально.
- Android генерирует public key и отправляет его на control plane.
- Control plane выбирает gateway, выдаёт VPN `/32`, выполняет provisioning через Gateway Agent.
- Gateway Agent добавляет peer через `wg set`.
- Android получает endpoint/public key/address и строит конфигурацию на устройстве.
- Android сохраняет конфигурацию encrypted локально с Android Keystore.
- VPN подключается; handshake и RX/TX видны на gateway.
- Full-tunnel и Selected Apps проверены владельцем: в Selected Apps счётчик переданных байтов на gateway возрастал при использовании выбранных приложений.

После этого M2.3a был добавлен, пройдены проверки и вручную проверен повторный provisioning после restart control plane.

### Проверки после M2.3a

Владелец сообщил:

```text
pytest server/tests -q : 18 passed
./gradlew :app:testDebugUnitTest : BUILD SUCCESSFUL
./gradlew :app:assembleDebug : BUILD SUCCESSFUL
./gradlew :app:lintDebug : BUILD SUCCESSFUL
```

Затем был пройден реальный restart test:

- SQLite содержал Android device ID;
- `client_address = 10.67.0.2/32`;
- `provisioned = 1`;
- `device_token_hash` имел длину 64 hex-символа (SHA-256 hex digest);
- public key Android совпадал с peer на `tunnelpilot0`;
- после restart control plane повторный `Provision device` прошёл с тем же Device ID/address и peer сохранился/был повторно применён через `wg set`.

Это реальный успешный dev-тест, но не означает production readiness.

### Текущий известный незакрытый подэтап

M2.3b — key rotation был спроектирован/упакован в `TunnelPilot_m2_3b_key_rotation.zip`, но владелец не подтвердил в переписке, что применил пакет и прогнал тесты. **Проверь GitHub/local tree.** Предлагаемый endpoint из того плана: `POST /v1/devices/{device_id}/rotate` с `X-Device-Token`. Не принимай наличие этого endpoint на веру.

---

## 3. Архитектура

### High-level diagram

```text
┌──────────────────────────────┐
│ Android app: TunnelPilot      │
│ Kotlin + Jetpack Compose      │
│                              │
│ SecureIdentityStore           │
│  - device ID                  │
│  - WG private key             │
│  - device token               │
│  - Android Keystore AES-GCM   │
│                              │
│ ControlPlaneClient            │
│ WireGuardConfigFactory        │
│ WireGuardManager / GoBackend  │
└──────────────┬───────────────┘
               │ HTTP JSON (dev LAN only)
               ▼
┌──────────────────────────────┐
│ FastAPI Control Plane :8000   │
│ server/app/main.py            │
│                              │
│ server catalog + health       │
│ auth, allocation, SQLite      │
│ orchestration to gateway      │
└──────────────┬───────────────┘
               │ HTTP + Bearer gateway token
               ▼
┌──────────────────────────────┐
│ Gateway Agent :8787           │
│ server/gateway_agent/app.py   │
│ WireGuardController           │
│ allowlisted `wg` commands     │
└──────────────┬───────────────┘
               │ `wg set` / `wg show`
               ▼
┌──────────────────────────────┐
│ Linux WireGuard interface     │
│ tunnelpilot0 / UDP 51820      │
│ 10.67.0.1/24                  │
│ forwarding + NAT              │
└──────────────┬───────────────┘
               ▼
            Internet
```

### Trust boundaries

- Android is the only place where the client private key should be created/used. Never upload private key to control plane, gateway agent, GitHub, logs or chat.
- Control plane stores only client public key and a **hash** of the per-device opaque authentication token, not the plaintext token.
- Android stores private key and device token locally encrypted with AES/GCM using a key in Android Keystore.
- Control plane is the only app component that orchestrates registrations/addresses; gateway agent is the privileged boundary that can execute restricted WireGuard peer operations.
- Gateway agent API must not be exposed to the public Internet. Keep localhost/private management network or behind a proper authenticated, encrypted management channel.
- Current local HTTP endpoints and root-launched gateway agent are development setup, not production configuration.

---

## 4. Repository map and important files

Use this as a starting index, then inspect actual current tree with `find`, `rg`, `git ls-files`.

### Android app

- `app/build.gradle.kts` — Android/Kotlin/Compose/dependencies/lint/build types.
- `app/src/main/AndroidManifest.xml` — VPN service, network permission, app declarations, backup exclusions.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/MainActivity.kt` — Compose UI tabs (`VPN`, `Apps`, `Config`, `Setup`) and app controls.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/MainViewModel.kt` — UI state, provisioning, Connect/Disconnect, Selected Apps, serialized VPN operations and reconnect logic.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/WireGuardManager.kt` — wraps WireGuard backend, Config parser and tunnel lifecycle.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/WireGuardTunnel.kt` — WireGuard `Tunnel` implementation and state callback.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/ConfigEditor.kt` — adds/removes `IncludedApplications` directives for per-app routing.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/data/AppSettingsStore.kt` — routing mode, selected apps, control-plane URL.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/data/SecureConfigStore.kt` — encrypted persisted WireGuard config.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/data/InstalledAppsRepository.kt` — installed/launchable app list (confirm exact path in current tree).
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/provisioning/ControlPlaneClient.kt` — HTTP JSON registration request, `X-Device-Token` header on authenticated re-registration, response parsing.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/provisioning/ControlPlaneModels.kt` — `RegisteredServer`, `RegistrationResult` including `deviceToken`.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/provisioning/ProvisioningState.kt` — Compose-facing provisioning state.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/provisioning/SecureIdentityStore.kt` — persistent Device ID, encrypted WG private key and device token.
- `app/src/main/java/com/blawhi3929bd/tunnelpilot/provisioning/WireGuardConfigFactory.kt` — creates `[Interface]` and `[Peer]` config from local private key, client address, server endpoint/public key.
- `app/src/main/java/com/wireguard/crypto/TunnelPilotKeyGenerator.kt` — local WireGuard Curve25519 key generation (confirm actual source path).
- `wireguard-tunnel/`, `third_party/wireguard-tunnel/` — vendored/buildable WireGuard tunnel module or upstream material. Inspect Gradle settings rather than assuming layout.

### Python server

- `server/app/main.py` — FastAPI control plane, device-token validation, server health/capacity, allocation orchestration and revocation.
- `server/app/storage.py` — `DeviceStore` SQLite schema/transactions/address allocation.
- `server/gateway_agent/app.py` — Gateway Agent endpoints and auth.
- `server/gateway_agent/models.py` — validated Pydantic request/response models.
- `server/gateway_agent/wireguard.py` — validates client base64 key and `/32` address; calls fixed `wg` argument list without shell interpolation.
- `server/tests/test_devices.py` — control-plane registration/auth/provision/revoke tests.
- `server/tests/test_storage.py` — persistent SQLite and IP allocation tests.
- `server/tests/test_gateway_health.py` — peer count and health/capacity tests.
- `server/tests/test_server_health.py` — server catalog health probing.
- `server/requirements.txt` — runtime Python dependency pins.
- `server/requirements-dev.txt` — pytest/httpx dev requirements.

### Infra/docs

- `infra/wireguard/dev-lan-gateway.sh` — creates development Linux WireGuard gateway (`tunnelpilot0`, `/24`, UDP 51820, NAT/forwarding). **Do not run repeatedly against an already working interface unless you understand its side effects.**
- `infra/smoke/m2-control-plane-gateway.sh` — development smoke-test for control-plane/gateway peer provisioning.
- `docs/M2_GATEWAY_TEST.md` — earlier manual gateway test guide; may be stale compared with M2.2 flow.
- `docs/M2_2_E2E.md` — repeatable E2E setup guide (read/update as needed).
- `.gitignore` — should ignore `.venv`, build outputs, `server/data/*.db`, and `server/data/*.db-*`.
- `README.md`, `server/README.md` — inspect and reconcile stale claims. A GitHub snapshot of `server/README.md` still said registration was in-memory after SQLite had been added; update this rather than propagating stale docs.

---

## 5. Technical stack (confirmed at last review)

### Android

- Kotlin/JVM with Java 17 target.
- Android Gradle Plugin (the last lint report showed 9.1.1); Gradle wrapper (last confirmed output: 9.3.1).
- `compileSdk = 37`, `targetSdk = 37`, `minSdk = 24`.
- Jetpack Compose + Material 3; Compose BOM last inspected at `2026.09.00`.
- AndroidX Activity Compose `1.13.0`; lifecycle ViewModel/runtime Compose `2.11.0`; `androidx.core:core-ktx:1.19.1`.
- `kotlinx-coroutines-android:1.11.0`.
- WireGuard Android Tunnel Library integrated as project module (`:wireguard-tunnel`). Uses GoBackend/userspace implementation where required.
- JUnit 4.13.2 and Compose UI testing dependencies.
- Core library desugaring enabled (`desugar_jdk_libs:2.1.5`).
- Release type currently configures minification and resource shrinking; do not assume release signing is set up.

### Backend

- Python; user dev environment showed Python 3.14.7.
- FastAPI `0.117.1`.
- Uvicorn Standard `0.37.0`.
- Pydantic `2.13.5`.
- HTTPX `0.28.1`.
- pytest `8.4.2` in development requirements.
- SQLite (`sqlite3` standard library), database class `DeviceStore`.
- Linux `wireguard-tools` (`wg`, `wg-quick`), `iptables`/`iptables-nft`, systemd.
- Fish shell on Arch/CachyOS; repo normally at `~/Projects/PilotTunnelVPN`.
- Android SDK was at `/opt/android-sdk`; NDK in prior environment `/opt/android-sdk/ndk/27.2.12479018`. Re-check before relying on those absolute paths in a new Codespace.

---

## 6. Current functionality by subsystem

### Android client functionality

- Native Android VPN permission path (`VpnService.prepare`).
- WireGuard backend wrapper with connect/disconnect and statistics.
- Full tunnel `AllowedIPs = 0.0.0.0/0`.
- Selected Apps mode via WireGuard's `IncludedApplications` allow list. Only selected packages go through VPN; other apps use their usual network path. The tunnel remains active; it is not an app-foreground monitor.
- Installed app selector/search.
- UI traffic counters (RX/TX) when active.
- Encrypted config storage and local client identity credential storage.
- Manual config save/import path.
- Setup screen for control-plane URL and provisioning.
- Operation `Mutex` and wait-for-backend-state logic were added to mitigate disconnect/reconnect races.

### Control plane functionality

- `GET /healthz`.
- `GET /v1/servers`: enabled server catalog enriched with Gateway Agent health and capacity (`health_status`, `peer_count`, `peer_capacity`, `capacity_remaining`) and sorted to prefer healthy/high-capacity gateway.
- `POST /v1/devices`: validate client public key, select a healthy gateway, allocate a stable unique `/32`, issue an opaque per-device token (only on first successful response), persist its hash, call Gateway Agent to provision peer, return gateway information and client address.
- `DELETE /v1/devices/{device_id}`: remove peer then delete stored device state; admin `TUNNELPILOT_CONTROL_PLANE_TOKEN` configuration currently optional.
- `DeviceStore` uses SQLite at `TUNNELPILOT_DATABASE_PATH`, default relative path `server/data/tunnelpilot.db`; it creates the parent directory, uses SQLite WAL mode and performs `BEGIN IMMEDIATE` for address allocation/insertion.
- Device token is high entropy via `secrets.token_urlsafe(32)`; SHA-256 hex digest is stored and compared using `hmac.compare_digest`.
- Device authentication header: `X-Device-Token` on repeat registration.
- Existing device should get the same address and same gateway assignment, then peer provisioning is reapplied idempotently with `wg set`.

### Gateway Agent functionality

- `GET /healthz`: reports `status`, `interface`, `wireguard_available`, `peer_count`, `peer_capacity`, `capacity_remaining`.
- `POST /v1/peers`: authenticated peer addition from public key + one IPv4 `/32` AllowedIP.
- `DELETE /v1/peers?public_key=...`: authenticated peer removal.
- Uses `TUNNELPILOT_GATEWAY_AGENT_TOKEN`, `TUNNELPILOT_WG_INTERFACE` (default `tunnelpilot0`), `TUNNELPILOT_WG_BINARY` (default `wg`), `TUNNELPILOT_WG_MAX_PEERS` (default 240).
- Public key validated as strict standard base64 decoding to 32 bytes. Allowed IP must be a single IPv4 `/32` and not arbitrary CIDR, reducing command abuse.
- It passes argument arrays to subprocess; must continue to avoid shell interpolation.

---

## 7. Local development environment and known working E2E configuration

These values describe the **development setup seen during testing**, not production secrets. Public keys and LAN addresses are not private-key material. Re-check them before use because DHCP addresses/network settings can change.

- Linux gateway interface: `tunnelpilot0`.
- Gateway VPN address: `10.67.0.1/24`.
- WireGuard UDP port: `51820`.
- LAN address of user's PC seen during test: `192.168.1.85`.
- Server public key at that point: `X+HVHErh7vmw0KCd4L2zpsWdAZc7VPZziLi42xYR2Bs=`.
- Android test device LAN address previously seen: `192.168.1.88`.
- Android VPN address from persistent DB: `10.67.0.2/32`.
- Android WG public key from DB/gateway: `nfdhYUw1uH6b48DjbqW9kOoQAQRcCewyyjm033mmexw=`.
- Device ID from real test: `aea6670d-c4f8-48db-8bd3-8dd246998d3d` (identifying metadata; do not use hardcoded in tests).
- Control plane HTTP port `8000`; Gateway Agent `8787`, normally bound to `127.0.0.1`.
- Gateway Agent had to be launched with sufficient privileges to run `wg show` and `wg set`; a development test used root-running Uvicorn because ordinary process permissions caused `health_status = degraded`. **Do not blindly copy this as production deployment architecture.** Use a narrow privileged helper/systemd/capabilities/restricted service in production.
- The Android phone was initially on mobile data and could not access `192.168.1.85:8000`; switching to the same Wi-Fi as the PC fixed provisioning. Make sure the Android is on a network that can reach the PC LAN address and firewall allows the control-plane port.

### Typical dev environment values

- `TUNNELPILOT_GATEWAY_AGENT_URL=http://127.0.0.1:8787`
- `TUNNELPILOT_GATEWAY_AGENT_TOKEN=<same random token passed to gateway agent>`
- `TUNNELPILOT_WG_INTERFACE=tunnelpilot0`
- `TUNNELPILOT_WG_MAX_PEERS=240`
- `TUNNELPILOT_SERVER_ID=dev-lan-1`
- `TUNNELPILOT_SERVER_REGION=dev-lan`
- `TUNNELPILOT_SERVER_HOSTNAME=<current PC LAN IP reachable by Android>`
- `TUNNELPILOT_SERVER_PORT=51820`
- `TUNNELPILOT_SERVER_PUBLIC_KEY=<read from /etc/wireguard/tunnelpilot0-server_public.key>`
- `TUNNELPILOT_VPN_ADDRESS_POOL=10.67.0.0/24`
- `TUNNELPILOT_VPN_GATEWAY_ADDRESS=10.67.0.1`
- `TUNNELPILOT_DATABASE_PATH=<absolute path recommended; current default is relative>`

Never save the gateway private key or gateway-agent token in Git. Do not paste the Android private key or device token into the agent prompt.

### Commands for a local dev session (fish examples)

First confirm the interface exists:

```fish
sudo wg show tunnelpilot0
ip -4 addr show tunnelpilot0
sudo systemctl is-active wg-quick@tunnelpilot0
```

Gateway Agent (in a dedicated terminal; development only):

```fish
cd ~/Projects/PilotTunnelVPN
set -x TP_GATEWAY_TOKEN (openssl rand -hex 32)
printf '%s\n' $TP_GATEWAY_TOKEN | sudo tee /tmp/tunnelpilot-gateway-agent-token >/dev/null
sudo chmod 600 /tmp/tunnelpilot-gateway-agent-token

sudo env \
  TUNNELPILOT_GATEWAY_AGENT_TOKEN="$TP_GATEWAY_TOKEN" \
  TUNNELPILOT_WG_INTERFACE=tunnelpilot0 \
  TUNNELPILOT_WG_MAX_PEERS=240 \
  ~/Projects/PilotTunnelVPN/.venv/bin/uvicorn \
  server.gateway_agent.app:app --host 127.0.0.1 --port 8787
```

For a second terminal, read the same token:

```fish
set -x TUNNELPILOT_GATEWAY_AGENT_TOKEN (sudo cat /tmp/tunnelpilot-gateway-agent-token)
```

Control plane (dedicated terminal; ensure all variables are exported into this process):

```fish
cd ~/Projects/PilotTunnelVPN
set -x TUNNELPILOT_GATEWAY_AGENT_URL http://127.0.0.1:8787
set -x TUNNELPILOT_GATEWAY_AGENT_TOKEN (sudo cat /tmp/tunnelpilot-gateway-agent-token)
set -x TUNNELPILOT_SERVER_ID dev-lan-1
set -x TUNNELPILOT_SERVER_REGION dev-lan
set -x TUNNELPILOT_SERVER_HOSTNAME (ip -4 route get 1.1.1.1 | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
set -x TUNNELPILOT_SERVER_PORT 51820
set -x TUNNELPILOT_SERVER_PUBLIC_KEY (sudo cat /etc/wireguard/tunnelpilot0-server_public.key)
set -x TUNNELPILOT_VPN_ADDRESS_POOL 10.67.0.0/24
set -x TUNNELPILOT_VPN_GATEWAY_ADDRESS 10.67.0.1
# Strongly recommended: use absolute stable DB path, for example:
set -x TUNNELPILOT_DATABASE_PATH "$HOME/Projects/PilotTunnelVPN/server/data/tunnelpilot.db"
~/Projects/PilotTunnelVPN/.venv/bin/uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

Health checks from another terminal:

```fish
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/v1/servers | python3 -m json.tool
cd ~/Projects/PilotTunnelVPN
sqlite3 server/data/tunnelpilot.db 'SELECT device_id, client_address, provisioned, length(device_token_hash) FROM devices;'
sudo wg show tunnelpilot0
```

**Note on SQLite relative paths:** the default `server/data/tunnelpilot.db` is relative to the control-plane process's current working directory. Earlier, running `sqlite3 server/data/tunnelpilot.db` from `~` failed because it looked under `~/server/data`. `cd ~/Projects/PilotTunnelVPN` before using this relative path, or configure an absolute `TUNNELPILOT_DATABASE_PATH`. For long-lived use, prefer an absolute path.

To see all peers:

```fish
sudo wg show tunnelpilot0
```

Do not run `dev-lan-gateway.sh` again over a live gateway unless deliberately rebuilding the setup. It generates keys/config and adjusts firewall/NAT settings.

---

## 8. API and protocol notes

### Control Plane

`GET /healthz`

Simple control-plane liveness response.

`GET /v1/servers`

Returns enabled gateways with their externally routable hostname, server public key, port, health status and capacity telemetry. Gateway Agent API URL is intentionally excluded from public `Server` response.

`POST /v1/devices`

Expected request body:

```json
{
  "device_id": "uuid-or-stable-install-id",
  "client_public_key": "base64-wireguard-public-key",
  "app_version": "0.2.0-debug"
}
```

On first registration (dev flow), expected response contains:

```json
{
  "status": "accepted",
  "device_id": "...",
  "client_address": "10.67.0.2/32",
  "provisioned": true,
  "device_token": "opaque-secret-returned-once",
  "server": {
    "id": "dev-lan-1",
    "region": "dev-lan",
    "hostname": "192.168.1.85",
    "public_key": "gateway-public-key",
    "port": 51820
  }
}
```

For subsequent registration, Android adds `X-Device-Token: <stored-token>`; server returns same address and does not reveal token again (`device_token` null/absent). Token is encrypted locally by `SecureIdentityStore`.

`DELETE /v1/devices/{device_id}`

Device revoke. Current backend code gates this via optional `TUNNELPILOT_CONTROL_PLANE_TOKEN`; because the token is optional in development, production must change policy so admin revocation is authenticated and cannot be reached anonymously.

### Gateway Agent

`GET /healthz`: no auth currently needed for health endpoint on the locally bound dev agent; reports WireGuard availability and capacity.

`POST /v1/peers` body:

```json
{
  "public_key": "base64-public-key",
  "allowed_ip": "10.67.0.2/32"
}
```

Requires `Authorization: Bearer <gateway-agent-token>`.

`DELETE /v1/peers?public_key=<base64-public-key>` requires the same Bearer token.

Control plane should pass only public key and `/32` address to the agent. Never send private key to the gateway agent.

---

## 9. Known risks / code review findings to address

This section is especially important. Treat these as real review leads to verify against the current code, not necessarily fully reproduced runtime bugs.

### P0 — Partial registration can strand a device if gateway provisioning fails

In the current M2.3a flow, the server appears to:

1. generate `device_token` and persist only its hash with the device row;
2. attempt the gateway `/v1/peers` call;
3. if the gateway request fails, return HTTP error;
4. because of the HTTP error, the client never receives the plaintext token;
5. future attempts for that device ID enter the existing-record path and require a token the client may never have received.

This can strand a partially registered device. Fix as an early M2.3b task. Design a recoverable, transactional/idempotent provisioning flow, including remote side-effects and timeouts. Possible directions: explicit pending/active registration states plus a securely designed recoverable claim/retry protocol; or rollback/delete pending registration and reconcile possible orphan peers on failure. Carefully reason about race conditions, lost responses, and ambiguous gateway success. Never make existing active devices anonymously re-claimable by `device_id` alone.

Add tests for: gateway unavailable on first request; gateway executes `wg set` but HTTP response is lost; retry with same device ID/public key; concurrent duplicate registrations; ensure no unowned permanent reservation and no unauthenticated takeover.

### P0 — Admin/revocation auth defaults permissive

`TUNNELPILOT_CONTROL_PLANE_TOKEN` is optional and `_require_control_plane_auth` allows requests through if it is unset. For dev this is convenient; for a control plane bound to `0.0.0.0` it means admin delete is not protected by an admin Bearer token. Before production, enforce credentials for destructive/admin endpoints (prefer fail-closed at startup or route-specific required auth). Do not just hardcode a static token into the repository.

### P0 — Current control plane uses plaintext HTTP in dev

The Android client can send `X-Device-Token` in HTTP headers; on shared or hostile Wi-Fi plaintext control-plane traffic can expose credentials. LAN-only development was used. For Internet deployment use HTTPS with valid certificate or an authenticated encrypted channel. Gateway agent must remain private; use TLS/mTLS or secure management network between control plane and gateway. Clearly distinguish development mode from production mode.

### P1 — Key rotation must be failure-safe across DB and gateway

Rotation touches Android secure key store, control-plane database, and gateway peer. These operations cannot be one local transaction. Design a recoverable state machine, old/new peer overlap strategy, idempotency keys or operation records, rollback/retry after timeouts, and token continuity. Avoid a window that permanently locks the device out or drops connectivity unnecessarily. Keep same VPN address and assigned gateway unless there is an explicit migration.

### P1 — Gateway agent execution model

The working dev agent ran with enough privilege to execute `wg` against `tunnelpilot0`; root-running whole Uvicorn makes the process sensitive. For production, use minimal privilege: dedicated systemd service/user/capabilities or a narrow privileged helper with strict command surface, secure token loading and network restriction. Do not listen on `0.0.0.0` for the gateway agent.

### P1 — Durable DB path / backups / SQLite lifecycle

`DATABASE_PATH` is relative by default. For systemd/containers, set an absolute path. Ensure parent directory ownership/permissions, DB/WAL/SHM backup/restore, migration tests and concurrent access behavior. Never commit `server/data/tunnelpilot.db` or `*.db-wal`/`*.db-shm`. `.gitignore` was updated to ignore `server/data/*.db` and `server/data/*.db-*`, verify it stays present.

### P1 — Reconcile persisted DB with real WireGuard state

SQLite and gateway are different state stores. Gateway reboot may wipe peers if WireGuard config does not `SaveConfig` or peer provisioning is not persisted; control-plane DB may say `provisioned=1` while peer is absent. Repeat registration currently re-applies `wg set` and can repair a peer, but there is no confirmed fleet reconciliation job. Build a safe reconciliation process with metrics/lock/rate limits and idempotent operations, not destructive blind sync.

### P1 — IP allocation / server assignment

SQLite allocation has transaction protection and unique addresses, but verify behaviour if address pool/env changes, gateway address changes, multiple gateways/pools are introduced, or DB records refer to a removed server. Client addresses should remain reserved on revoke according to explicit product policy or be freed intentionally with audit safety. Multi-gateway address allocation needs subnet ownership semantics, not one global simple pool.

### P2 — Device identity semantics

`device_id` is a stable install identity, not strong hardware identity. Android app reinstall/Keystore loss can make the client lose the token/private key while server has existing record. Define a lost-device/recovery protocol (admin revoke/reset/new install) rather than an unsafe unauthenticated rebind. Key rotation is not equivalent to recovery after lost token.

### P2 — README drift

At least one read of `server/README.md` after SQLite work still described registration as an in-memory store. Update docs to say SQLite is the current dev persistence backend and list its current limitations. Keep README and runbooks in sync with real commands/environment variables.

### Performance issue is open, not yet diagnosed

Owner reported very slow loading after successful VPN connection. Measurements collected while tunnelling:

- `adb shell ping -c 20 10.67.0.1`: 0% loss but average ~147 ms, max ~817 ms, huge jitter.
- PC `ping -c 20 1.1.1.1`: average ~75 ms, max ~319 ms, also unstable.
- Android-to-Internet direct baseline before VPN: first test avg ~23.5 ms, max ~56 ms and showed duplicate ICMP replies; results were noisy.
- WireGuard tunnel packets with payloads 1300/1380/1400 bytes had replies and no loss in the tests shown.
- `ip -s link`: `tunnelpilot0` counters showed RX/TX errors increasing (`47` RX errors / `390` TX errors at that snapshot, zero drops), while Wi-Fi `wlo1` had zero errors and a small TX drop count. These counters do not by themselves prove the cause.
- Owner suspects Wi-Fi could be slow and prioritised “it works” over immediate performance fixing. Root cause is not confirmed. Do not casually change MTU/iptables/DNS without controlled before/after tests. Retest direct LAN ping, gateway ping and internet baseline; test full tunnel versus Selected Apps using actual selected app; inspect `wg show`, CPU, network signal/rate and per-interface counters.

---

## 10. Product / design decisions

### Selected Apps is not “toggle VPN based on foreground app”

Current Selected Apps is a WireGuard/Android allow list fixed when the VPN connection is established. Selected packages use the tunnel; others use their normal network route; the tunnel remains active. When selection changes, reconnect is required. This was deliberately chosen as the reliable baseline rather than repeatedly monitoring foreground app and repeatedly starting/stopping VPN.

### Smart Apps / Smart Auto — future phase

Long-term inspiration: apps that automatically use VPN for some applications/services while sensitive or local apps bypass it. Desired possible behavior:

- user selects apps to route through VPN;
- banks/marketplaces or explicitly excluded apps can stay direct (requires clear precedence policy);
- optional “smart auto” tries to connect/disconnect based on app needs only if it can be implemented within Android background-execution and VPN policy constraints;
- no premature AccessibilityService or continuous polling just to imitate competitors;
- begin with robust per-app allow/block list UX, then investigate lifecycle-aware automatic behaviour and Android restrictions.

The current Selected Apps implementation should be viewed as v1 baseline. Do not claim full foreground-based Smart Auto already exists.

### Monetization future phase

- Free: core working VPN, potentially ads inside app, perhaps fair usage/server choices; never intentionally broken service.
- Premium: remove ads, more/priority gateways, possible advanced connection controls, more regions.
- Ads must not be injected into other apps, proxied/manipulated, or used to tamper with ad delivery.
- Consider regional ad demand/payment availability before committing to a single provider. Verify current laws, platform policies, SDK consent requirements and real availability at monetization implementation time.
- No real ad SDK or premium payment code currently confirmed.

---

## 11. Roadmap

Track this as working plan, not as statements that every item is already implemented.

### M2.2 — E2E (completed and manually verified)

- [x] Working Linux WireGuard gateway.
- [x] Gateway Agent with peer provisioning.
- [x] Control plane server catalog and server health/capacity.
- [x] Android local key generation and provisioning.
- [x] Real handshake, internet and selected-app routing manually verified.
- [x] Build/lint/test pipeline green.

### M2.3a — persistent state + device auth (implemented, tested)

- [x] SQLite `DeviceStore`.
- [x] Stable address allocation.
- [x] Device token issued on first registration; only SHA-256 hash stored server-side.
- [x] Android encrypts token using Android Keystore-backed AES-GCM.
- [x] Authenticated repeat registration keeps device ID/address.
- [x] Repeat provisioning calls `wg set` idempotently to repair lost peer.
- [x] Health/capacity-aware server selection.
- [x] Local restart scenario verified by owner.
- [ ] Improve failure recovery around initial token issuance/provisioning (important issue above).

### M2.3b — lifecycle hardening / key rotation (next)

First inspect whether the previously created key-rotation patch is already in local/current branch. If not, implement deliberately:

- [ ] Add an authenticated and well-tested key-rotation protocol.
- [ ] Generate new private key **on Android only**; private key never leaves device.
- [ ] Authenticate rotation with existing `X-Device-Token`.
- [ ] Keep Device ID, device token (unless intentionally rotated), server assignment and VPN `/32` stable by default.
- [ ] Define safe old/new peer transition and rollback/retry behaviour when Gateway Agent or DB fails.
- [ ] Persist rotation operation state / audit metadata where needed.
- [ ] Remove old peer only when new path is safely installed and client has switched or the protocol can recover cleanly.
- [ ] Add UI action only after server/API lifecycle is tested; show meaningful state/errors; never accidentally invalidate the current config before new credentials are safely stored.
- [ ] Test lost response, gateway timeout, DB failure, duplicate request, wrong token, changed public key, and old peer cleanup.
- [ ] Run real dev-gateway smoke test and Android connect/handshake after rotation.

### M2.3c — revoke and recovery

- [ ] Distinguish user-initiated revoke, admin revoke, lost device/token, and ordinary disconnect.
- [ ] Strong admin auth required by default.
- [ ] Decide whether revoked addresses are released or tombstoned.
- [ ] Handle gateway removal failure: don't silently delete DB record before peer removal outcome is known; use pending revocation/tombstone/outbox state so retries are safe.
- [ ] Add operation/audit records without logging secrets.
- [ ] Support restoring/reconciling peer after gateway reboot.
- [ ] Rate limit administrative operations and avoid ID-enumeration leaks.

### M2.4 — deployment and reliability

- [ ] Move from ad-hoc terminals to reproducible service definitions (systemd/container later) with stable absolute DB path and protected token file/env source.
- [ ] Secure management path between control plane and gateway.
- [ ] HTTPS for client-facing control plane; dev cleartext stays LAN-only.
- [ ] Liveness/readiness checks; meaningful health states.
- [ ] Stable DB migrations, backups and restore drill.
- [ ] Connection diagnostics: handshake age, byte counters, endpoint reachability, DNS status, MTU troubleshooting.
- [ ] Multi-gateway catalog and safe region selection, latency/capacity scoring and failover policy.

### M3 — client product polish

- [ ] Onboarding and clear first connection flow.
- [ ] Quick Connect and visible connection status/last handshake.
- [ ] Searchable app selector improvements, Selected Apps UX, persistent reconnect affordance.
- [ ] Connection diagnostics and MTU/DNS/route validation.
- [ ] Auto reconnect/network-change handling, connection service lifecycle.
- [ ] Privacy-safe crash reporting/analytics only with appropriate disclosures and opt-in where required.
- [ ] Settings and clear privacy/permissions explanations.

### M3.5 — Smart Apps / Smart Auto investigation

- [ ] Product policy for include/exclude rules and default routes.
- [ ] Prototype Android lifecycle-aware state behaviour without unsafe foreground polling.
- [ ] Verify platform background-service restrictions, user-visible foreground notification and store policy before choosing architecture.
- [ ] Test app selection across device restart, network switch, and process death.
- [ ] Keep manual Selected Apps path as robust fallback.

### M4 — monetization

- [ ] Decide provider based on current region availability and policy.
- [ ] Isolate ads from VPN transport/control plane.
- [ ] Explicit consent/privacy handling and no manipulation of third-party app traffic.
- [ ] Premium purchase validation and entitlements, if pursued.
- [ ] Unit/integration tests for paywall entitlement without making the free VPN unusable.

### M5 — release

- [ ] Threat model and security audit.
- [ ] Production TLS, secrets management, rate limiting, abuse prevention.
- [ ] Durable operational storage, backups/monitoring/alerts.
- [ ] Android release signing protected outside Git.
- [ ] VPN permission/service review, Play Console declaration/listing/policy and data-safety/privacy documents.
- [ ] Closed beta and staged rollout.

---

## 12. Test and build commands

Run from repository root, normally `~/Projects/PilotTunnelVPN`.

### Python

```bash
.venv/bin/python -m pip install -r server/requirements-dev.txt
.venv/bin/pytest server/tests -q
```

If the project test configuration or Python environment differs, use `python -m pytest` inside `.venv`; do not assume system pytest imports the repo path correctly. Do not test against the live user DB; tests should use `tmp_path`/isolated SQLite DB.

### Android

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
./gradlew :app:lintDebug
```

Install on connected dev device only when explicitly wanted:

```bash
adb devices
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Package observed in dev setup: `com.blawhi3929bd.tunnelpilot.debug`; version observed: `0.2.0-debug`, versionCode 2. Verify in current build instead of hardcoding assumptions.

### E2E smoke test

`infra/smoke/m2-control-plane-gateway.sh` uses environment variables including `DEVICE_ID` and `CLIENT_PUBLIC_KEY`, calls control plane/gateway, checks health and provisioning and can use `CLEANUP=1` to revoke test device. Read the script before running it. Do not reuse Android's production/current public key or overwrite a live peer during smoke test. Use a throwaway key generated specifically for the test:

```bash
TEST_PRIVATE_KEY="$(wg genkey)"
CLIENT_PUBLIC_KEY="$(printf '%s\n' "$TEST_PRIVATE_KEY" | wg pubkey)"
export CLIENT_PUBLIC_KEY
export DEVICE_ID="m22-smoke-$(date +%s)"
export CLEANUP=1
./infra/smoke/m2-control-plane-gateway.sh
unset TEST_PRIVATE_KEY CLIENT_PUBLIC_KEY DEVICE_ID CLEANUP
```

Be aware that the smoke script may persist its own test registration in a dev DB if cleanup fails. Confirm peer removal and DB cleanup. The private key is not needed for this specific control-plane/gateway-only smoke test; do not print or save it.

### Gateway checks

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/v1/servers | python -m json.tool
sudo wg show tunnelpilot0
ip -4 addr show tunnelpilot0
```

### Android performance diagnostics (only with controlled comparison)

```bash
adb shell ping -c 20 10.67.0.1
adb shell ping -c 20 1.1.1.1
adb shell cmd wifi status
adb shell top -n 1 -b | head -30
adb logcat -d | grep -iE 'wireguard|GoBackend|tunnelpilot' | tail -100
sudo ip -s link show tunnelpilot0
sudo ip -s link show wlo1
```

A shell ping is not always a good per-app routing test because `adb shell` runs as a different UID than a selected app. Test actual traffic from the selected app too.

---

## 13. Code/UX style decisions

- The owner prefers exact actionable changes and commands. Explain file paths/insertion points if editing manually, but in a full coding workspace, edit files directly and provide a concise summary plus test evidence.
- Preserve the Kotlin Compose architecture unless a concrete issue warrants a refactor.
- Prefer readable APIs, sealed state types, testable storage/provisioning units, explicit timeouts and typed errors.
- Do not put huge business logic in Compose UI composables.
- Keep HTTP client off Android main thread; current VM uses IO dispatcher.
- Avoid logging client private keys, device token, gateway token or auth headers.
- Use strict validation for all server input and fixed argument vectors for external commands.
- Keep server state transitions explicit: `pending`, `active/provisioned`, `rotation_pending`, `revocation_pending`, etc. if needed; don’t rely on a single boolean when recovery requires richer states.
- Keep control-plane API schemas and Android models in sync. A backend change that adds fields, headers or endpoint semantics must update `ControlPlaneClient`, models, tests and docs.
- Update `server/README.md`/`docs/` whenever procedure/config variables change.
- No unsupported assertion that the tunnel is “production secure” before HTTPS, privileged boundary isolation, admin auth, rollback, restore and threat model are done.

---

## 14. Recommended skills and MCP for a coding agent

The objective is to add high-value tools, not a huge MCP zoo. Most of the actual work is local repository edits + shell tests; a local shell is more important than an MCP for these tasks.

### Essential / high priority

#### A. Context7 (MCP or docs skill)

**Why:** APIs for Android/Gradle/Compose, Kotlin coroutines, FastAPI/Pydantic/HTTPX/SQLite and other versions change. Context7 helps fetch current, version-relevant docs instead of relying on model memory.

Official docs:
- https://context7.com/docs/clients/cli
- https://context7.com/docs/resources/all-clients
- https://context7.com/install

Common setup entry points (pick the one for the actual agent and follow current prompts/docs):

```bash
npx ctx7 setup
# Or specific integrations where supported:
npx ctx7 setup --codex
npx ctx7 setup --claude
npx ctx7 setup --opencode
npx ctx7 setup --cli --antigravity
```

Don't install conflicting duplicate Context7 MCP configurations in both global and project settings unless needed. Keep authentication keys outside the repository.

#### B. GitHub MCP or authenticated GitHub CLI

**Why:** inspect commits/branches/files, create issues/PRs, review CI status and connect code work to project history. However, GitHub MCP permissions vary by app/token. The GitHub connector used in a prior ChatGPT session returned HTTP 403 for write operations; therefore prefer the user's local authenticated `git push`/`gh` where MCP write permission is not guaranteed.

Official server: https://github.com/github/github-mcp-server

Recommended access policy:
- read repository, commits, issues and PRs by default;
- write only what is actually needed;
- never give the agent a broad personal token if a narrower credential is possible;
- no secrets in tool output or commits.

### Useful optional tools

#### C. Android Studio MCP (only if using Android Studio's agent)

Official guide: https://developer.android.com/studio/gemini/add-mcp-server

Can connect supported remote MCP servers such as GitHub or Figma inside Android Studio. It is not a substitute for Gradle/ADB shell commands. The official guide notes integration limitations (for example, stdio MCP transport not supported by Android Studio's MCP host), so verify compatibility before configuring a local stdio server there.

#### D. Figma MCP (later, when UI redesign begins)

Useful for screen inspection/prototyping/design-to-code once M3 UX work starts. Low priority now because M2.3 is mainly backend security/lifecycle rather than visual design. Official connection example appears in Android Studio MCP docs and Figma's own MCP documentation: https://developer.android.com/studio/gemini/add-mcp-server

#### E. Filesystem/local shell MCP

Only install if the coding environment does not already provide safe filesystem and terminal access. The agent must have access to repository files and run:
- `git`;
- `.venv` Python/pytest;
- `./gradlew`;
- `adb`;
- optionally `wg`, `sqlite3`, `curl`, `ip`, `nft` in a controlled dev environment.

Avoid an unrestricted filesystem server that can read the entire home directory or private keys. Scope tools to the repository where possible.

#### F. Security tools (prefer CLI first)

Good future additions: Ruff/format checks, Bandit or Semgrep for Python, dependency vulnerability audit, Android dependency review and secret scanning. Start with CI/CLI tools; add an MCP wrapper only if it materially helps the agent consume the results. Do not add a security scanner just for decoration without defining how findings are tested and triaged.

### Skills to create in the repo

The reusable Agent Skills standard uses a `SKILL.md` directory structure. Current common discovery location for Codex/OpenCode/Antigravity is `.agents/skills`; OpenCode also supports `.opencode/skills` and `.claude/skills`; Claude Code supports `.claude/skills`. Official references:

- Codex customization: https://learn.chatgpt.com/docs/customization/overview
- OpenCode skills: https://docs.opencode.ai/docs/skills/
- Claude Agent Skills: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Antigravity skills: https://antigravity.google/docs/ide/skills

Prefer a shared `.agents/skills/` directory for cross-agent skills, but verify discovery behaviour in the installed version of each CLI. Keep root `AGENTS.md` short and universal; keep long procedures in skills.

Recommended skills:

1. **`.agents/skills/tunnelpilot-dev/SKILL.md`** — repo navigation, architecture, safe command use, build/test workflow, config/env setup, branch/diff/commit discipline.
2. **`.agents/skills/android-vpn-regression/SKILL.md`** — WireGuard connection, routing mode, config parsing, VPN permission, ADB diagnostics, tests for Full Tunnel and Selected Apps, reconnection and device network changes.
3. **`.agents/skills/provisioning-lifecycle/SKILL.md`** — device registration/token auth, address allocation, gateway agent calls, idempotency, DB+gateway failure recovery, key rotation, revoke, reconciling state after restart.
4. **`.agents/skills/security-review/SKILL.md`** — threat model checklist, secret handling, endpoint auth, TLS boundaries, least privilege, subprocess argument validation, data retention and logs.
5. **`.agents/skills/release-validation/SKILL.md`** — run pytest + Gradle checks, verify lint, inspect APK/version, check Git status and ignored DB/key material, create release notes without overstating verified behaviour.

Avoid installing random community skills without reviewing each `SKILL.md` and scripts. Skills are executable instructions in practice and can be a supply-chain risk if they direct unsafe actions.

---

## 15. Official references worth using

- WireGuard embedding / Android tunnel library: https://www.wireguard.com/embedding/ and https://git.zx2c4.com/wireguard-android
- Android VPN service and per-app VPN: https://developer.android.com/develop/connectivity/vpn
- FastAPI testing with `TestClient` and HTTPX: https://fastapi.tiangolo.com/tutorial/testing/
- GitHub MCP server: https://github.com/github/github-mcp-server
- Context7 setup/docs: https://context7.com/docs/clients/cli
- Codex project guidance and skills: https://learn.chatgpt.com/docs/customization/overview
- OpenCode skills: https://docs.opencode.ai/docs/skills/
- Claude Agent Skills: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Antigravity skills: https://antigravity.google/docs/ide/skills
- Google Play VpnService policy (re-check during release/monetization, not as a replacement for policy/legal review): https://support.google.com/googleplay/android-developer/answer/12564964

---

## 16. Suggested root `AGENTS.md` content

This should be kept concise in the repository, and this complete handoff can live in `docs/AGENT_HANDOFF.md` or be attached to the coding agent at session start.

```markdown
# TunnelPilot engineering rules

- Read `docs/AGENT_HANDOFF.md` (or the attached TunnelPilot handoff) before significant work.
- Treat Git source as the source of truth; inspect `git status`, HEAD and existing diffs before editing.
- Do not discard user changes, run destructive shell commands, or use `git add .` automatically.
- Never commit private keys, device tokens, gateway tokens, secrets, signing credentials, APK credentials or SQLite data.
- Client WireGuard private keys are generated/stored only on Android; backend receives public keys only.
- Keep Gateway Agent private; do not expose it to the Internet. Avoid root-running whole processes in production.
- For server changes run `.venv/bin/pytest server/tests -q`.
- For Android changes run `./gradlew :app:testDebugUnitTest`, `./gradlew :app:assembleDebug`, and `./gradlew :app:lintDebug`.
- Do not report tests as passing unless they were run; state what was not tested.
- Make lifecycle/security changes idempotent and failure-recoverable across SQLite + Gateway Agent side effects.
- Use Context7/official docs for version-sensitive APIs.
- Update tests and docs with API/schema/config changes.
```

---

## 17. Paste-this prompt for a new coding agent

> You are taking over TunnelPilot, an Android-first WireGuard VPN with a FastAPI control plane and a Linux gateway agent. Start by reading the attached `TunnelPilot Agent Handoff` carefully. Then inspect the actual repository and report current branch/HEAD/status and whether its code matches the handoff. Do not reset, clean, or overwrite unknown local modifications. Establish a baseline by running Python tests and Android Gradle checks if the workspace has the required SDK/environment.
>
> The last confirmed GitHub HEAD in this handoff is `9afa03a077cde93c57176ffeca537f76f228b668`. M2.2 end-to-end provisioning and M2.3a SQLite/device-token persistence were manually verified with a real Android device + Linux `tunnelpilot0`. Key rotation was planned as M2.3b but is not confirmed in the last GitHub HEAD; determine whether it exists before doing anything.
>
> Primary next task: continue M2.3b lifecycle/security work. First address the failure-recovery concern where the server can persist a one-time device-token hash before gateway provisioning completes, potentially failing to deliver the plaintext token to Android if provisioning fails. Design and test a recoverable idempotent protocol without enabling device takeover. Then implement authenticated WireGuard key rotation with failure-safe DB/gateway state transitions, stable client address and device authentication, rollback/retry semantics, and tests for failures/timeouts/duplicate requests. Add Android UI only after backend lifecycle is reliable. Protect revocation with fail-closed admin auth and note that current dev HTTP is not suitable for production.
>
> Before implementing, inspect `server/app/main.py`, `server/app/storage.py`, `server/gateway_agent/*`, Android provisioning classes, current tests and docs. Use small reviewable changes. Run `pytest server/tests -q` plus `./gradlew :app:testDebugUnitTest`, `./gradlew :app:assembleDebug`, and `./gradlew :app:lintDebug`; update docs; inspect Git diff/status; never commit secrets, private keys, database files or local env. Tell the owner exactly what changed and what was tested, without claiming production readiness prematurely.

---

## 18. Definition of done for the next meaningful milestone

M2.3b is not done merely because the endpoint returns HTTP 200. Require all of the following:

- repeat provisioning after process restart continues to work;
- rotation works with correct device token and rejects missing/invalid token;
- private key is generated locally and never leaves Android;
- no database state can become permanently unusable when gateway returns an error/timeouts;
- re-trying a rotation request is safe;
- the gateway has the correct active public key/AllowedIP after rotation;
- old peer is removed at a well-defined point and cleanup retries exist;
- address and server assignment remain unchanged unless explicit migration is invoked;
- revocation and rotation are mutually safe if racing;
- SQLite migrations and old schema are covered by tests;
- unit/API tests pass, Android test/build/lint pass;
- one real development gateway/Android rotation is verified with a fresh handshake and traffic;
- docs and operational steps are updated;
- no local DB/token/private key is staged.

**Production-readiness bar:** M2.3b is still not production release readiness. HTTPS, mandatory admin authentication, privileged gateway isolation, durable state recovery/reconciliation, abuse controls, monitoring, privacy disclosures and deployment automation remain required.
