"""High-level control layer for the ELM327 emulator.

The upstream project exposes a powerful Python object but primarily controls it
through an interactive shell. This wrapper turns those controls into a stable,
thread-safe API suitable for the web dashboard.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from elm.elm import Elm


class ELM327Wrapper:
    PARAMETER_SPECS: Dict[str, Dict[str, Any]] = {
        "engine_rpm": {"range": (0.0, 8000.0), "pid": "RPM", "encode": "rpm"},
        "vehicle_speed": {"range": (0.0, 255.0), "pid": "SPEED", "encode": "byte"},
        "throttle_position": {"range": (0.0, 100.0), "pid": "THROTTLE_POS", "encode": "percent"},
        "engine_coolant_temp": {"range": (-40.0, 215.0), "pid": "COOLANT_TEMP", "encode": "temperature"},
        "engine_load": {"range": (0.0, 100.0), "pid": "ENGINE_LOAD", "encode": "percent"},
        "fuel_level": {"range": (0.0, 100.0), "pid": "FUEL_LEVEL", "encode": "percent"},
        "intake_manifold_pressure": {"range": (0.0, 255.0), "pid": "INTAKE_PRESSURE", "encode": "byte"},
        "timing_advance": {"range": (-64.0, 63.5), "pid": "TIMING_ADVANCE", "encode": "timing"},
        "oxygen_sensor_voltage": {"range": (0.0, 1.275), "pid": "O2_B1S2", "encode": "oxygen"},
        "mass_air_flow": {"range": (0.0, 655.35), "pid": "MAF", "encode": "maf"},
    }

    DEFAULT_VALUES: Dict[str, float] = {
        "engine_rpm": 800.0,
        "vehicle_speed": 0.0,
        "throttle_position": 16.0,
        "engine_coolant_temp": 90.0,
        "engine_load": 18.0,
        "fuel_level": 65.0,
        "intake_manifold_pressure": 38.0,
        "timing_advance": 8.0,
        "oxygen_sensor_voltage": 0.45,
        "mass_air_flow": 3.2,
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger("elm327.web")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

        self._lock = threading.RLock()
        self.emulator = Elm(serial_port=None, batch_mode=True)
        self.emulator.logger = self.logger
        self.emulator.threadState = self.emulator.THREAD.ACTIVE

        self.running = True
        self.paused = False
        self.last_execution_time = 0.0
        self._request_number = 0
        self._parameter_values = dict(self.DEFAULT_VALUES)
        self._history: Deque[Dict[str, Any]] = deque(maxlen=250)
        self._faults: Dict[str, Any] = {
            "no_response": False,
            "drop_every_n": 0,
            "malformed_every_n": 0,
            "latency_jitter_ms": 0,
            "next_command_delay_seconds": 0.0,
        }
        self._apply_all_parameter_overrides()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clamp_byte(value: float) -> int:
        return max(0, min(255, int(round(value))))

    @classmethod
    def _encode_value(cls, encoding: str, value: float) -> str:
        if encoding == "rpm":
            raw = max(0, min(65535, int(round(value * 4))))
            return f"{raw >> 8:02X} {raw & 0xFF:02X}"
        if encoding == "percent":
            return f"{cls._clamp_byte(value * 255 / 100):02X}"
        if encoding == "temperature":
            return f"{cls._clamp_byte(value + 40):02X}"
        if encoding == "timing":
            return f"{cls._clamp_byte((value + 64) * 2):02X}"
        if encoding == "maf":
            raw = max(0, min(65535, int(round(value * 100))))
            return f"{raw >> 8:02X} {raw & 0xFF:02X}"
        if encoding == "oxygen":
            # Mode 01 PID 15: A/200 volts, B is short-term trim.
            return f"{cls._clamp_byte(value * 200):02X} FF"
        return f"{cls._clamp_byte(value):02X}"

    def _apply_parameter_override(self, parameter: str, value: float) -> None:
        spec = self.PARAMETER_SPECS[parameter]
        encoded = self._encode_value(spec["encode"], value)
        # The upstream emulator checks this dictionary before the static PID answer.
        self.emulator.answer[spec["pid"]] = f"<pos_answer>{encoded}</pos_answer>"

    def _apply_all_parameter_overrides(self) -> None:
        for parameter, value in self._parameter_values.items():
            self._apply_parameter_override(parameter, value)

    @staticmethod
    def _normalize_result(raw_result: Any) -> List[str]:
        if raw_result is None:
            return []
        if isinstance(raw_result, str):
            return [raw_result]
        if isinstance(raw_result, (list, tuple)):
            return [str(item) for item in raw_result if item is not None]
        return [str(raw_result)]

    def _execute_emulator_command(self, command: str, protocol: str) -> str:
        if protocol.lower() != "auto":
            protocol_command = f"ATSP{protocol}".replace(" ", "").upper()
            header, data, response_xml = self.emulator.handle_request(protocol_command)
            if response_xml is not None:
                self.emulator.handle_response(
                    response_xml,
                    request_header=header,
                    request_data=data,
                )

        normalized_command = re.sub(r"\s+", "", command).upper()
        request_header, request_data, response_xml = self.emulator.handle_request(normalized_command)
        if response_xml is None:
            return ""
        computed = self.emulator.handle_response(
            response_xml,
            request_header=request_header,
            request_data=request_data,
        )
        return "".join(self._normalize_result(computed))

    def _record_history(
        self,
        command: str,
        response: str,
        outcome: str,
        execution_time: float,
    ) -> None:
        self._history.appendleft(
            {
                "timestamp": self._now(),
                "command": command,
                "response": response,
                "outcome": outcome,
                "execution_time": round(execution_time, 6),
                "scenario": self.emulator.scenario,
            }
        )

    def process_command(self, command: str, protocol: str = "auto") -> Dict[str, Any]:
        command = command.strip()
        if not command:
            raise ValueError("Command cannot be empty")

        started = time.perf_counter()
        outcome = "success"
        response = ""

        with self._lock:
            self._request_number += 1
            request_number = self._request_number

            if not self.running:
                outcome = "stopped"
                response = "EMULATOR STOPPED\r>"
            elif self.paused:
                outcome = "paused"
                response = "NO DATA\r>"
            else:
                one_shot_delay = float(self._faults["next_command_delay_seconds"] or 0)
                self._faults["next_command_delay_seconds"] = 0.0
                jitter_ms = int(self._faults["latency_jitter_ms"] or 0)
                if one_shot_delay > 0:
                    time.sleep(one_shot_delay)
                if jitter_ms > 0:
                    time.sleep(random.uniform(0, jitter_ms) / 1000)

                drop_every = int(self._faults["drop_every_n"] or 0)
                malformed_every = int(self._faults["malformed_every_n"] or 0)
                if self._faults["no_response"] or (drop_every > 0 and request_number % drop_every == 0):
                    outcome = "dropped"
                    response = "NO DATA\r>"
                elif malformed_every > 0 and request_number % malformed_every == 0:
                    outcome = "malformed"
                    response = "41 ZZ 00\r>"
                else:
                    response = self._execute_emulator_command(command, protocol)
                    if not response:
                        outcome = "empty"

            self.last_execution_time = time.perf_counter() - started
            self._record_history(command, response, outcome, self.last_execution_time)

            response_bytes = [list(response.encode("ascii", errors="ignore"))] if response else []
            return {
                "status": "success" if outcome == "success" else "simulated_fault",
                "outcome": outcome,
                "response": response,
                "response_bytes": response_bytes,
                "execution_time": self.last_execution_time,
                "request_number": request_number,
            }

    def set_ecu_value(self, parameter: str, value: float) -> bool:
        with self._lock:
            spec = self.PARAMETER_SPECS.get(parameter)
            if spec is None:
                return False
            minimum, maximum = spec["range"]
            if value < minimum or value > maximum:
                return False
            self._parameter_values[parameter] = float(value)
            self._apply_parameter_override(parameter, float(value))
            return True

    def get_ecu_value(self, parameter: str) -> Optional[float]:
        return self._parameter_values.get(parameter)

    def get_all_values(self) -> Dict[str, float]:
        return dict(self._parameter_values)

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            self.emulator.set_defaults()
            self.emulator.reset(0)
            self.emulator.set_sorted_obd_msg()
            self.emulator.threadState = self.emulator.THREAD.ACTIVE
            self.running = True
            self.paused = False
            self._request_number = 0
            self._faults.update(
                no_response=False,
                drop_every_n=0,
                malformed_every_n=0,
                latency_jitter_ms=0,
                next_command_delay_seconds=0.0,
            )
            self._parameter_values = dict(self.DEFAULT_VALUES)
            self._apply_all_parameter_overrides()
            self._history.clear()
            return self.get_status()

    def control(self, action: str) -> Dict[str, Any]:
        action = action.lower()
        with self._lock:
            if action == "start":
                self.running = True
                self.paused = False
                self.emulator.threadState = self.emulator.THREAD.ACTIVE
            elif action == "pause":
                self.paused = True
                self.emulator.threadState = self.emulator.THREAD.PAUSED
            elif action == "resume":
                self.running = True
                self.paused = False
                self.emulator.threadState = self.emulator.THREAD.ACTIVE
            elif action == "stop":
                self.running = False
                self.paused = False
                self.emulator.threadState = self.emulator.THREAD.STOPPED
            elif action == "reset":
                return self.reset()
            else:
                raise ValueError(f"Unsupported action: {action}")
            return self.get_status()

    def available_scenarios(self) -> List[str]:
        return sorted(name for name in self.emulator.ObdMessage.keys() if name != "AT")

    def set_scenario(self, scenario: str) -> Dict[str, Any]:
        with self._lock:
            if scenario not in self.available_scenarios():
                raise ValueError(f"Unknown scenario: {scenario}")
            self.emulator.set_sorted_obd_msg(scenario)
            self._apply_all_parameter_overrides()
            return self.get_status()

    def set_timing(self, values: Dict[str, float]) -> Dict[str, Any]:
        with self._lock:
            if "response_delay" in values:
                self.emulator.delay = max(0.0, float(values["response_delay"]))
            if "p1" in values:
                self.emulator.interbyte_out_delay = max(0.0, float(values["p1"]))
            if "p2" in values:
                self.emulator.delay = max(0.0, float(values["p2"]))
            if "p3" in values:
                self.emulator.multiframe_timer = max(0.0, float(values["p3"]))
            if "p4" in values:
                self.emulator.max_req_timeout = max(0.0, float(values["p4"]))
            return self.get_status()

    def set_choice(self, mode: str, weights: Optional[List[float]] = None) -> Dict[str, Any]:
        with self._lock:
            mode = mode.lower()
            if mode == "random":
                self.emulator.choice_mode = self.emulator.Choice.RANDOM
            elif mode == "sequential":
                self.emulator.choice_mode = self.emulator.Choice.SEQUENTIAL
            else:
                raise ValueError("Choice mode must be random or sequential")
            clean_weights = [float(weight) for weight in (weights or [1.0]) if float(weight) >= 0]
            self.emulator.choice_weights = clean_weights or [1.0]
            return self.get_status()

    def set_faults(self, faults: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            for key in self._faults:
                if key in faults:
                    value = faults[key]
                    if key == "no_response":
                        self._faults[key] = bool(value)
                    elif key in {"drop_every_n", "malformed_every_n", "latency_jitter_ms"}:
                        self._faults[key] = max(0, int(value))
                    else:
                        self._faults[key] = max(0.0, float(value))
            return self.get_status()

    def apply_fault_preset(self, preset: str) -> Dict[str, Any]:
        presets: Dict[str, Dict[str, Any]] = {
            "healthy": {
                "scenario": "default",
                "faults": {"no_response": False, "drop_every_n": 0, "malformed_every_n": 0, "latency_jitter_ms": 0},
                "delay": 0.0,
            },
            "engine_off": {
                "scenario": "engineoff",
                "faults": {"no_response": False, "drop_every_n": 0, "malformed_every_n": 0, "latency_jitter_ms": 0},
                "delay": 0.0,
            },
            "slow_adapter": {
                "scenario": "default",
                "faults": {"no_response": False, "drop_every_n": 0, "malformed_every_n": 0, "latency_jitter_ms": 1200},
                "delay": 0.8,
            },
            "intermittent_drop": {
                "scenario": "default",
                "faults": {"no_response": False, "drop_every_n": 5, "malformed_every_n": 0, "latency_jitter_ms": 250},
                "delay": 0.15,
            },
            "malformed_frames": {
                "scenario": "default",
                "faults": {"no_response": False, "drop_every_n": 0, "malformed_every_n": 4, "latency_jitter_ms": 100},
                "delay": 0.0,
            },
            "ecu_unavailable": {
                "scenario": "default",
                "faults": {"no_response": True, "drop_every_n": 0, "malformed_every_n": 0, "latency_jitter_ms": 0},
                "delay": 0.0,
            },
        }
        if preset not in presets:
            raise ValueError(f"Unknown fault preset: {preset}")
        config = presets[preset]
        self.set_scenario(config["scenario"])
        self.emulator.delay = float(config["delay"])
        self.set_faults(config["faults"])
        return self.get_status()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._history)[: max(1, min(limit, 250))]

    def get_counters(self) -> Dict[str, Any]:
        counters: Dict[str, Any] = {}
        for key, value in self.emulator.counters.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                counters[key] = value
            else:
                counters[key] = str(value)
        counters["web_requests"] = self._request_number
        return counters

    def get_status(self) -> Dict[str, Any]:
        state = "stopped" if not self.running else "paused" if self.paused else "running"
        choice_mode = "random" if self.emulator.choice_mode == self.emulator.Choice.RANDOM else "sequential"
        return {
            "state": state,
            "running": self.running,
            "paused": self.paused,
            "scenario": self.emulator.scenario,
            "scenarios": self.available_scenarios(),
            "interface": "web-api",
            "client_connected": True,
            "request_count": self._request_number,
            "last_execution_time": self.last_execution_time,
            "timing": {
                "p1": self.emulator.interbyte_out_delay,
                "p2": self.emulator.delay,
                "p3": self.emulator.multiframe_timer,
                "p4": self.emulator.max_req_timeout,
                "response_delay": self.emulator.delay,
            },
            "choice": {
                "mode": choice_mode,
                "weights": list(self.emulator.choice_weights),
            },
            "faults": dict(self._faults),
            "version": self.get_version(),
        }

    def get_version(self) -> str:
        return str(getattr(self.emulator, "version", "unknown"))
