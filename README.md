# ELM327 Emulator Web Control Panel

A browser-based control and fault-injection interface built on top of
[Ircama/ELM327-emulator](https://github.com/Ircama/ELM327-emulator).

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
- Manual fault controls for latency, one-shot delays, dropped commands, and
  malformed replies
- Raw OBD-II command console
- Live WebSocket state, request history, counters, and active task visibility
- Dark and light themes
- Docker Compose development setup

## Quick start

### Docker Compose

```bash
git clone https://github.com/lotfinity/ELM327-emulator-web-API.git
cd ELM327-emulator-web-API
docker compose up --build
```

Open:

- Control panel: `http://localhost:3000`
- FastAPI documentation: `http://localhost:8000/docs`

### Manual setup

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd control-panel
bun install
NEXT_PUBLIC_API_URL=http://localhost:8000 bun run dev
```

## Dashboard controls

### Runtime state

The dashboard can enable, pause, resume, stop, or reset command processing.
These controls operate the in-process web emulator. They do not start a
separate serial or TCP listener.

### ECU parameter overrides

The following values can be changed while the emulator is running:

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
Next.js control panel
        │ REST + WebSocket
        ▼
FastAPI control layer
        │ direct Python calls
        ▼
Ircama/ELM327-emulator
```

The current web API processes commands directly in-process. A separate future
adapter can expose the same controlled emulator over TCP, a pseudo-terminal, or
a serial interface for external applications that require a physical-port-style
connection.

## Current limitations

- Persistent WebSockets are intended for local or containerized Uvicorn
  deployments; traditional serverless deployments may not support them.
- Start and stop currently govern API command processing rather than a dedicated
  TCP or serial listener.
- Plugin/task visibility is available, but plugin flows depend on what the
  upstream emulator loads and activates in the selected execution mode.
- The dashboard is a development and simulation tool, not a replacement for
  safety-critical vehicle diagnostics.

## Technology

- Python 3.10+
- ELM327-emulator 3.0.5
- FastAPI
- Next.js and TypeScript
- shadcn/ui
- Docker Compose

## License and attribution

This fork retains the original project's licensing and attribution files.
The emulator engine comes from
[Ircama/ELM327-emulator](https://github.com/Ircama/ELM327-emulator), and this
web project originated from
[rakshitbharat/ELM327-emulator-web-API](https://github.com/rakshitbharat/ELM327-emulator-web-API).
