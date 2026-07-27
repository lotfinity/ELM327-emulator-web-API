# Bluetooth Classic SPP setup on Linux

This phase makes the emulator appear to Android as a Bluetooth Classic ELM327-style serial adapter.

It registers the standard Serial Port Profile UUID:

```text
00001101-0000-1000-8000-00805F9B34FB
```

BlueZ owns SDP and the RFCOMM listener. When a phone connects, BlueZ passes the accepted socket to the FastAPI process through `org.bluez.Profile1.NewConnection`.

## Requirements

- Linux host
- Bluetooth adapter supporting BR/EDR (Bluetooth Classic)
- BlueZ running on the host
- FastAPI/Uvicorn deployment; traditional serverless hosts cannot expose local Bluetooth hardware

Install and start BlueZ on Debian or Ubuntu:

```bash
sudo apt update
sudo apt install -y bluez rfkill
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth

bluetoothctl list
bluetoothctl show
```

The output should show a controller such as `hci0`.

## Run directly on the Linux host

```bash
git switch feat/bluetooth-spp-transport

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip 'setuptools<81' wheel
env -u GITHUB_RUN_NUMBER python -m pip install --no-build-isolation -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Start the frontend in another terminal:

```bash
cd control-panel
bun install
NEXT_PUBLIC_API_URL=http://localhost:8000 bun run dev
```

Open `http://localhost:3000`, configure the Bluetooth panel, and press **Start Bluetooth SPP**.

## Run with Docker Compose

BlueZ remains on the host. The Bluetooth override mounts the host system D-Bus socket into the backend container:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.bluetooth.yml \
  up --build
```

Bluetooth does not autostart by default. Start it from the dashboard, or use:

```bash
ELM_BLUETOOTH_AUTOSTART=true \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.bluetooth.yml \
  up --build
```

Rootless Docker or restrictive D-Bus policies may block BlueZ profile registration. Running the backend directly on the host is the most reliable first test.

## Pair the Android phone

### Desktop Linux with a pairing dialog

Leave **Headless auto-pair** disabled. Your desktop Bluetooth agent will display the normal pairing dialog.

### Headless Linux host

Enable **Headless auto-pair** temporarily in the dashboard. The default legacy PIN is `1234`.

This mode accepts nearby pairing requests while the adapter is discoverable. Disable it after the development phone has been paired.

### Android steps

1. Open Android Bluetooth settings.
2. Pair with **LotoT ELM327**, or the device name configured in the dashboard.
3. Enter `1234` if Android requests a legacy PIN.
4. Open Torque, Car Scanner, or another OBD-II application.
5. Select **Bluetooth / Bluetooth Classic**, not BLE.
6. Select the paired **LotoT ELM327** device.

The dashboard should change from `REGISTERED` to `CONNECTED` and display the phone address and live byte counters.

## Test expected commands

Most OBD applications initialize with commands similar to:

```text
ATZ
ATE0
ATL0
ATS0
ATH0
ATSP0
0100
010C
010D
```

The same scenario, PID overrides, response timing, randomization, and fault injection configured in the web dashboard are applied to Bluetooth requests.

## API controls

```text
GET  /api/v1/bluetooth/status
POST /api/v1/bluetooth/start
POST /api/v1/bluetooth/stop
POST /api/v1/bluetooth/disconnect
```

Example start request:

```bash
curl -X POST http://localhost:8000/api/v1/bluetooth/start \
  -H 'Content-Type: application/json' \
  -d '{
    "service_name": "LotoT ELM327",
    "adapter": "hci0",
    "channel": 1,
    "discoverable": true,
    "pairable": true,
    "auto_pair": false,
    "legacy_pin": "1234",
    "require_authentication": false,
    "require_authorization": false,
    "manage_adapter": true
  }'
```

## Troubleshooting

### `No BlueZ Bluetooth adapter was found`

```bash
sudo systemctl status bluetooth
rfkill list bluetooth
bluetoothctl list
```

Unblock the adapter and verify that it appears as `hci0` or update the adapter field in the dashboard.

### Cannot connect to the system bus

Verify that `/run/dbus/system_bus_socket` exists. With Docker, use `docker-compose.bluetooth.yml`.

### D-Bus permission denied

First run the backend directly on the host. If that succeeds, the problem is the container or host D-Bus policy rather than the emulator.

### Profile already exists or channel is busy

Stop other emulator processes and press **Stop Bluetooth** before restarting. If needed:

```bash
sudo systemctl restart bluetooth
```

### Android sees the device but the OBD app cannot connect

- Remove the pairing from Android and pair again after the SPP profile is registered.
- Keep RFCOMM channel `1` for maximum clone-adapter compatibility.
- Disable **Require secure link** for applications that use insecure RFCOMM sockets.
- Confirm the app is using Bluetooth Classic rather than BLE.

### BLE applications

This phase implements Bluetooth Classic SPP because it is the interface expected by traditional ELM327 Android applications. A BLE GATT transport is a separate later phase.

## Security note

Discoverable mode, insecure RFCOMM, and automatic pairing are development conveniences. Use them only on a controlled test host and disable discoverability and auto-pairing when testing is complete.
