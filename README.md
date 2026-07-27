# ELM327 Emulator Web Control Panel

A browser-based control, fault-injection, and Bluetooth Classic interface built
on top of [Ircama/ELM327-emulator](https://github.com/Ircama/ELM327-emulator).

The project combines a FastAPI backend with a Next.js control panel. It is
intended for developing and testing OBD-II clients without needing a vehicle or
physical ELM327 adapter for every test case.

![ELM327 Emulator GUI](docs/image.png)

## Features

- Real ELM327 command processing through the upstream emulator
- Adjustable ECU values that change actual PID responses
- Start, pause, resume, stop, and reset controls
- Runtime scenario selection, including `default`, `car`, and `engineoff`
- UDS P1, P2, P3, and P4 timing controls
- Sequential or weighted-random response selection
- Built-in fault presets for slow adapters, dropped requests, malformed frames,
  engine-off behavior, and unavailable ECUs
- Raw OBD-II command console
- Live WebSocket state, request history, counters, and active task visibility
- **Bluetooth Classic SPP server for Android OBD-II applications**
- BlueZ adapter, pairing, connection, and traffic controls in the dashboard
- Docker Compose development setup

## Quick start

The Bluetooth work currently lives on the stacked feature branch:

```bash
git clone https://github.com/lotfinity/ELM327-emulator-web-API.git
cd ELM327-emulator-web-API
git switch feat/bluetooth-spp-transport
```

### Standard Docker Compose

```bash
docker compose up --build
```

Open:

- Control panel: `http://localhost:3000`
- FastAPI documentation: `http://localhost:8000/docs`

### Docker Compose with Linux Bluetooth

BlueZ runs on the host. Use the Bluetooth override to mount the host system
D-Bus socket into the backend:

```bash
sudo apt install -y bluez rfkill
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth

docker compose \
  -f docker-compose.yml \
  -f docker-compose.bluetooth.yml \
  up --build
```

Then press **Start Bluetooth SPP** in the dashboard.

See [Bluetooth Classic SPP setup on Linux](docs/bluetooth-linux.md) for pairing,
headless operation, Android configuration, and troubleshooting.

### Manual setup

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip 'setuptools<81' wheel
env -u GITHUB_RUN_NUMBER python -m pip install --no-build-isolation -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`ELM327-emulator` 3.0.5 is currently supplied as a source distribution and its
setup script imports `pkg_resources`. Preparing setuptools and disabling pip's
minimal isolated build environment avoids that upstream packaging issue.

Frontend:

```bash
cd control-panel
bun install
NEXT_PUBLIC_API_URL=http://localhost:8000 bun run dev
```

## Bluetooth Classic SPP

The Bluetooth transport registers the standard Serial Port Profile UUID used by
traditional Android ELM327 applications:

```text
00001101-0000-1000-8000-00805F9B34FB
```

BlueZ performs SDP registration and accepts RFCOMM connections. The accepted
socket is handed to FastAPI through `org.bluez.Profile1.NewConnection` and uses
the same emulator instance as the web command console.

Supported serial behavior includes:

- Carriage-return and CRLF command framing
- ELM command echo controlled by `ATE0` and `ATE1`
- Blank-command repetition
- Standard `>` prompt termination
- One connected Bluetooth client at a time
- Live RX/TX byte and command counters
- The same PID overrides, scenarios, timing, and fault injection as the web API
- Optional headless auto-pairing with a configurable legacy PIN

This phase is Bluetooth Classic, not BLE GATT.

## Dashboard controls

### Runtime state

The dashboard can enable, pause, resume, stop, or reset command processing.
These controls affect commands from both the web API and Bluetooth transport.

### ECU parameter overrides

| Parameter | Range | Unit | OBD PID |
|---|---:|---|---|
| Engine RPM | 0–8000 | RPM | `01 0C` |
| Vehicle speed | 0–255 | km/h | `01 0D` |
| Throttle position | 0–100 | % | `01 11` |
| Coolant temperature | -40–215 | °C | `01 05` |
| Engine load | 0–100 | % | `01 04` |
| Fuel level | 0–100 | % | `01 2F` |
| Intake manifold pressure | 0–255 | kPa | `01 0B` |
| Timing advance | -64–63.5 | ° | `01 0E` |
| O2 sensor voltage | 0–1.275 | V | `01 15` |
| Mass air flow | 0–655.35 | g/s | `01 10` |

The backend encodes these values into ELM327 response bytes and installs them
through the upstream emulator's runtime PID-answer override mechanism.

### Fault presets

- `healthy`
- `engine_off`
- `slow_adapter`
- `intermittent_drop`
- `malformed_frames`
- `ecu_unavailable`

Custom fault settings can also drop every Nth command, corrupt every Nth reply,
add random latency, suppress all replies, or delay only the next command.

## API overview

### Commands and ECU values

```text
POST /api/v1/command
POST /api/v1/ecu/set-value
POST /api/v1/ecu/reset
GET  /api/v1/ecu/values
GET  /api/v1/ecu/value/{parameter}
```

### Emulator controls

```text
GET  /api/v1/status
POST /api/v1/control
GET  /api/v1/scenarios
POST /api/v1/scenario
POST /api/v1/timing
POST /api/v1/choice
```

### Bluetooth controls

```text
GET  /api/v1/bluetooth/status
POST /api/v1/bluetooth/start
POST /api/v1/bluetooth/stop
POST /api/v1/bluetooth/disconnect
```

### Faults and monitoring

```text
POST /api/v1/faults
POST /api/v1/faults/preset
GET  /api/v1/history
GET  /api/v1/counters
GET  /api/v1/tasks
WS   /api/v1/ws
```

The complete request and response schemas are available from Swagger at
`/docs`.

## Architecture

```text
Android OBD app
      │ Bluetooth Classic SPP / RFCOMM
      ▼
BlueZ ProfileManager1
      │ accepted socket via D-Bus
      ├──────────────────────────────┐
      ▼                              │
Bluetooth SPP transport              │
      │                              │
      ▼                              │
FastAPI control layer ◄── REST + WebSocket ── Next.js dashboard
      │ direct Python calls
      ▼
Ircama/ELM327-emulator
```

## Current limitations

- Bluetooth requires a Linux host with BlueZ and a BR/EDR-capable adapter.
- Traditional serverless deployments cannot expose host Bluetooth or persistent
  WebSockets.
- The Bluetooth transport supports one client because ELM327 state and AT
  settings are shared per adapter.
- BLE GATT, TCP listener, pseudo-terminal, and direct serial transports remain
  separate later phases.
- The dashboard is a development and simulation tool, not a replacement for
  safety-critical vehicle diagnostics.

## Technology

- Python 3.10+
- ELM327-emulator 3.0.5
- FastAPI
- dbus-next and BlueZ
- Next.js and TypeScript
- shadcn/ui
- Docker Compose

## License and attribution

This fork retains the original project's licensing and attribution files.
The emulator engine comes from
[Ircama/ELM327-emulator](https://github.com/Ircama/ELM327-emulator), and this
web project originated from
[rakshitbharat/ELM327-emulator-web-API](https://github.com/rakshitbharat/ELM327-emulator-web-API).
