from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel, Field

from app.elm327_wrapper import ELM327Wrapper


app = FastAPI(
    title="ELM327 Emulator Control API",
    description="Control, monitor, and inject faults into an ELM327 ECU emulator.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

elm327 = ELM327Wrapper()


class Command(BaseModel):
    command: str
    protocol: str = "auto"


class ECUValue(BaseModel):
    parameter: str
    value: float = Field(..., description="Value to set for the parameter")


class ControlRequest(BaseModel):
    action: str


class ScenarioRequest(BaseModel):
    scenario: str


class TimingRequest(BaseModel):
    response_delay: Optional[float] = None
    p1: Optional[float] = None
    p2: Optional[float] = None
    p3: Optional[float] = None
    p4: Optional[float] = None


class ChoiceRequest(BaseModel):
    mode: str
    weights: List[float] = Field(default_factory=lambda: [1.0])


class FaultRequest(BaseModel):
    no_response: Optional[bool] = None
    drop_every_n: Optional[int] = None
    malformed_every_n: Optional[int] = None
    latency_jitter_ms: Optional[int] = None
    next_command_delay_seconds: Optional[float] = None


class FaultPresetRequest(BaseModel):
    preset: str


def _defined_values(model: BaseModel) -> Dict[str, Any]:
    return {key: value for key, value in model.dict().items() if value is not None}


@app.get("/")
async def root():
    return {
        "name": "ELM327 Emulator Control API",
        "status": "ok",
        "docs": "/docs",
    }


@app.post("/api/v1/command")
async def send_command(command: Command):
    try:
        return elm327.process_command(command.command, command.protocol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Command processing failed: {exc}")


@app.get("/api/v1/status")
async def get_status():
    return {"status": "success", "emulator": elm327.get_status()}


@app.post("/api/v1/control")
async def control_emulator(request: ControlRequest):
    try:
        return {"status": "success", "emulator": elm327.control(request.action)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/ecu/reset")
async def reset_emulator():
    return {"status": "success", "emulator": elm327.reset()}


@app.get("/api/v1/scenarios")
async def get_scenarios():
    return {
        "status": "success",
        "scenarios": elm327.available_scenarios(),
        "active": elm327.get_status()["scenario"],
    }


@app.post("/api/v1/scenario")
async def set_scenario(request: ScenarioRequest):
    try:
        return {"status": "success", "emulator": elm327.set_scenario(request.scenario)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/timing")
async def set_timing(request: TimingRequest):
    try:
        return {"status": "success", "emulator": elm327.set_timing(_defined_values(request))}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/choice")
async def set_choice(request: ChoiceRequest):
    try:
        return {
            "status": "success",
            "emulator": elm327.set_choice(request.mode, request.weights),
        }
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/faults")
async def set_faults(request: FaultRequest):
    try:
        return {"status": "success", "emulator": elm327.set_faults(_defined_values(request))}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/faults/preset")
async def apply_fault_preset(request: FaultPresetRequest):
    try:
        return {
            "status": "success",
            "emulator": elm327.apply_fault_preset(request.preset),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/history")
async def get_history(limit: int = Query(50, ge=1, le=250)):
    return {"status": "success", "history": elm327.get_history(limit)}


@app.get("/api/v1/counters")
async def get_counters():
    return {"status": "success", "counters": elm327.get_counters()}


@app.post("/api/v1/ecu/set-value")
async def set_ecu_value(value: ECUValue):
    if elm327.set_ecu_value(value.parameter, value.value):
        return {
            "status": "success",
            "message": f"Value set for {value.parameter}",
            "values": elm327.get_all_values(),
        }
    raise HTTPException(status_code=400, detail=f"Invalid parameter or value: {value.parameter}")


@app.get("/api/v1/ecu/values")
async def get_all_values():
    return {"status": "success", "values": elm327.get_all_values()}


@app.get("/api/v1/ecu/value/{parameter}")
async def get_ecu_value(parameter: str):
    value = elm327.get_ecu_value(parameter)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Parameter not found: {parameter}")
    return {"status": "success", "parameter": parameter, "value": value}


handler = Mangum(app)
