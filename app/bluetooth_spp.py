"""Bluetooth Classic Serial Port Profile transport for the ELM327 emulator.

The transport registers the standard Bluetooth SPP UUID with BlueZ over the
system D-Bus. BlueZ handles SDP, RFCOMM listening, pairing/authorization and
passes accepted sockets to this process through ``Profile1.NewConnection``.

The module deliberately keeps BlueZ optional at runtime: importing the web API
works on non-Linux machines and on Linux hosts without a Bluetooth adapter. A
clear error is returned only when Bluetooth is explicitly started.
"""

import asyncio
import logging
import os
import platform
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from dbus_next import DBusError, Variant
from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next.service import ServiceInterface, method


BLUEZ_SERVICE = "org.bluez"
BLUEZ_ROOT = "/org/bluez"
PROFILE_PATH = "/com/lotot/elm327/profile"
AGENT_PATH = "/com/lotot/elm327/agent"
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

CommandHandler = Callable[[str, str], Dict[str, Any]]
EchoHandler = Callable[[], bool]


@dataclass
class BluetoothSPPConfig:
    service_name: str = "LotoT ELM327"
    adapter: str = "hci0"
    channel: int = 1
    discoverable: bool = True
    pairable: bool = True
    auto_pair: bool = False
    legacy_pin: str = "1234"
    require_authentication: bool = False
    require_authorization: bool = False
    manage_adapter: bool = True

    def update(self, values: Dict[str, Any]) -> None:
        for key, value in values.items():
            if value is None or not hasattr(self, key):
                continue
            setattr(self, key, value)
        self.service_name = str(self.service_name).strip() or "LotoT ELM327"
        self.adapter = str(self.adapter).strip() or "hci0"
        self.channel = int(self.channel)
        if not 1 <= self.channel <= 30:
            raise ValueError("RFCOMM channel must be between 1 and 30")
        self.legacy_pin = str(self.legacy_pin).strip() or "1234"
        if len(self.legacy_pin) > 16:
            raise ValueError("Bluetooth PIN cannot exceed 16 characters")


class BlueZSPPProfile(ServiceInterface):
    def __init__(self, transport: "BluetoothSPPTransport"):
        super().__init__("org.bluez.Profile1")
        self.transport = transport

    @method()
    def Release(self):
        self.transport.profile_released()

    @method()
    def NewConnection(self, device: "o", fd: "h", properties: "a{sv}"):
        self.transport.accept_connection(device, fd, properties)

    @method()
    def RequestDisconnection(self, device: "o"):
        self.transport.request_disconnection(device)

    @method()
    def Cancel(self):
        self.transport.profile_cancelled()


class BlueZPairingAgent(ServiceInterface):
    """Optional headless pairing agent.

    Auto-pairing is disabled by default because making a discoverable machine
    accept every nearby pairing request is a security trade-off. It is useful
    for a headless development host that is intentionally acting like a cheap
    ELM327 dongle.
    """

    def __init__(self, transport: "BluetoothSPPTransport"):
        super().__init__("org.bluez.Agent1")
        self.transport = transport

    def _ensure_enabled(self) -> None:
        if not self.transport.config.auto_pair:
            raise DBusError("org.bluez.Error.Rejected", "Automatic pairing is disabled")

    @method()
    def Release(self):
        self.transport.agent_released()

    @method()
    def RequestPinCode(self, device: "o") -> "s":
        self._ensure_enabled()
        return self.transport.config.legacy_pin

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        self.transport.note_pairing_event(device, f"PIN displayed: {pincode}")

    @method()
    def RequestPasskey(self, device: "o") -> "u":
        self._ensure_enabled()
        digits = "".join(character for character in self.transport.config.legacy_pin if character.isdigit())
        return int((digits or "1234")[:6])

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        self.transport.note_pairing_event(device, f"Passkey {passkey:06d}, entered digits: {entered}")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        self._ensure_enabled()
        self.transport.note_pairing_event(device, f"Confirmed passkey {passkey:06d}")

    @method()
    def RequestAuthorization(self, device: "o"):
        self._ensure_enabled()
        self.transport.note_pairing_event(device, "Pairing authorized")

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        self._ensure_enabled()
        self.transport.note_pairing_event(device, f"Authorized service {uuid}")

    @method()
    def Cancel(self):
        self.transport.note_pairing_event(None, "Pairing cancelled")


class BluetoothSPPTransport:
    def __init__(
        self,
        command_handler: CommandHandler,
        echo_handler: EchoHandler,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.command_handler = command_handler
        self.echo_handler = echo_handler
        self.logger = logger or logging.getLogger("elm327.bluetooth")
        self.config = BluetoothSPPConfig(
            service_name=os.getenv("ELM_BLUETOOTH_SERVICE_NAME", "LotoT ELM327"),
            adapter=os.getenv("ELM_BLUETOOTH_ADAPTER", "hci0"),
            channel=int(os.getenv("ELM_BLUETOOTH_CHANNEL", "1")),
            discoverable=os.getenv("ELM_BLUETOOTH_DISCOVERABLE", "true").lower() in {"1", "true", "yes", "on"},
            pairable=os.getenv("ELM_BLUETOOTH_PAIRABLE", "true").lower() in {"1", "true", "yes", "on"},
            auto_pair=os.getenv("ELM_BLUETOOTH_AUTO_PAIR", "false").lower() in {"1", "true", "yes", "on"},
            legacy_pin=os.getenv("ELM_BLUETOOTH_PIN", "1234"),
        )

        self._operation_lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bus: Optional[MessageBus] = None
        self._profile_manager: Any = None
        self._agent_manager: Any = None
        self._profile: Optional[BlueZSPPProfile] = None
        self._agent: Optional[BlueZPairingAgent] = None
        self._adapter_path: Optional[str] = None
        self._adapter_address: Optional[str] = None
        self._adapter_alias: Optional[str] = None
        self._registered = False
        self._agent_registered = False

        self._client_socket: Optional[socket.socket] = None
        self._client_task: Optional[asyncio.Task] = None
        self._client_device: Optional[str] = None
        self._connected_since: Optional[str] = None
        self._last_disconnected_at: Optional[str] = None
        self._last_command: Optional[str] = None

        self.state = "stopped"
        self.last_error: Optional[str] = None
        self.warnings: List[str] = []
        self.last_pairing_event: Optional[str] = None
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.commands = 0

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _variant_value(value: Any) -> Any:
        return value.value if isinstance(value, Variant) else value

    @staticmethod
    def _device_address(device_path: Optional[str]) -> Optional[str]:
        if not device_path or "/dev_" not in device_path:
            return device_path
        return device_path.rsplit("/dev_", 1)[-1].replace("_", ":")

    @property
    def available(self) -> bool:
        return platform.system() == "Linux"

    async def start(self, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        async with self._operation_lock:
            if self._registered:
                return self.get_status()

            self.config.update(values or {})
            if not self.available:
                raise RuntimeError("Bluetooth SPP transport requires Linux and BlueZ")

            self.state = "starting"
            self.last_error = None
            self.warnings = []
            self._loop = asyncio.get_running_loop()

            try:
                self._bus = await MessageBus(
                    bus_type=BusType.SYSTEM,
                    negotiate_unix_fd=True,
                ).connect()
                await self._locate_adapter()
                if self.config.manage_adapter:
                    await self._configure_adapter()
                await self._register_profile()
                if self.config.auto_pair:
                    await self._register_agent()
                self.state = "registered"
                return self.get_status()
            except Exception as exc:
                self.last_error = str(exc)
                self.state = "error"
                await self._cleanup_bus()
                raise RuntimeError(f"Unable to start Bluetooth SPP: {exc}") from exc

    async def stop(self) -> Dict[str, Any]:
        async with self._operation_lock:
            await self.disconnect_client()

            if self._agent_registered and self._agent_manager is not None:
                try:
                    await self._agent_manager.call_unregister_agent(AGENT_PATH)
                except Exception as exc:
                    self.warnings.append(f"Could not unregister pairing agent: {exc}")
                self._agent_registered = False

            if self._registered and self._profile_manager is not None:
                try:
                    await self._profile_manager.call_unregister_profile(PROFILE_PATH)
                except Exception as exc:
                    self.warnings.append(f"Could not unregister SPP profile: {exc}")
                self._registered = False

            await self._cleanup_bus()
            self.state = "stopped"
            return self.get_status()

    async def _cleanup_bus(self) -> None:
        if self._bus is not None:
            try:
                self._bus.unexport(PROFILE_PATH)
            except Exception:
                pass
            try:
                self._bus.unexport(AGENT_PATH)
            except Exception:
                pass
            try:
                self._bus.disconnect()
            except Exception:
                pass
        self._bus = None
        self._profile_manager = None
        self._agent_manager = None
        self._profile = None
        self._agent = None
        self._adapter_path = None

    async def _locate_adapter(self) -> None:
        assert self._bus is not None
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/")
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        object_manager = proxy.get_interface("org.freedesktop.DBus.ObjectManager")
        managed_objects = await object_manager.call_get_managed_objects()

        requested_suffix = f"/{self.config.adapter}"
        selected_path = None
        selected_properties: Dict[str, Any] = {}
        for path, interfaces in managed_objects.items():
            adapter_properties = interfaces.get("org.bluez.Adapter1")
            if adapter_properties is None:
                continue
            if path.endswith(requested_suffix):
                selected_path = path
                selected_properties = adapter_properties
                break
            if selected_path is None:
                selected_path = path
                selected_properties = adapter_properties

        if selected_path is None:
            raise RuntimeError("No BlueZ Bluetooth adapter was found")

        self._adapter_path = selected_path
        self._adapter_address = self._variant_value(selected_properties.get("Address"))
        self._adapter_alias = self._variant_value(selected_properties.get("Alias"))
        selected_name = selected_path.rsplit("/", 1)[-1]
        if selected_name != self.config.adapter:
            self.warnings.append(
                f"Requested adapter {self.config.adapter} was not found; using {selected_name}"
            )
            self.config.adapter = selected_name

    async def _set_adapter_property(self, name: str, variant: Variant) -> None:
        assert self._bus is not None and self._adapter_path is not None
        try:
            introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
            proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
            properties = proxy.get_interface("org.freedesktop.DBus.Properties")
            await properties.call_set("org.bluez.Adapter1", name, variant)
        except Exception as exc:
            self.warnings.append(f"Could not set adapter {name}: {exc}")

    async def _configure_adapter(self) -> None:
        await self._set_adapter_property("Powered", Variant("b", True))
        await self._set_adapter_property("Alias", Variant("s", self.config.service_name))
        await self._set_adapter_property("Pairable", Variant("b", bool(self.config.pairable)))
        await self._set_adapter_property("Discoverable", Variant("b", bool(self.config.discoverable)))
        if self.config.pairable:
            await self._set_adapter_property("PairableTimeout", Variant("u", 0))
        if self.config.discoverable:
            await self._set_adapter_property("DiscoverableTimeout", Variant("u", 0))
        self._adapter_alias = self.config.service_name

    async def _register_profile(self) -> None:
        assert self._bus is not None
        self._profile = BlueZSPPProfile(self)
        self._bus.export(PROFILE_PATH, self._profile)

        introspection = await self._bus.introspect(BLUEZ_SERVICE, BLUEZ_ROOT)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, BLUEZ_ROOT, introspection)
        self._profile_manager = proxy.get_interface("org.bluez.ProfileManager1")
        options = {
            "Name": Variant("s", self.config.service_name),
            "Role": Variant("s", "server"),
            "Channel": Variant("q", self.config.channel),
            "Version": Variant("q", 0x0102),
            "RequireAuthentication": Variant("b", bool(self.config.require_authentication)),
            "RequireAuthorization": Variant("b", bool(self.config.require_authorization)),
            "AutoConnect": Variant("b", False),
        }
        await self._profile_manager.call_register_profile(PROFILE_PATH, SPP_UUID, options)
        self._registered = True

    async def _register_agent(self) -> None:
        assert self._bus is not None
        self._agent = BlueZPairingAgent(self)
        self._bus.export(AGENT_PATH, self._agent)

        introspection = await self._bus.introspect(BLUEZ_SERVICE, BLUEZ_ROOT)
        proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, BLUEZ_ROOT, introspection)
        self._agent_manager = proxy.get_interface("org.bluez.AgentManager1")
        await self._agent_manager.call_register_agent(AGENT_PATH, "NoInputNoOutput")
        await self._agent_manager.call_request_default_agent(AGENT_PATH)
        self._agent_registered = True

    def accept_connection(self, device: str, fd: int, properties: Dict[str, Variant]) -> None:
        if self._client_socket is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            raise DBusError("org.bluez.Error.Rejected", "An ELM327 client is already connected")

        try:
            client_socket = socket.socket(fileno=fd)
            client_socket.setblocking(False)
        except Exception as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            raise DBusError("org.bluez.Error.Rejected", f"Invalid RFCOMM socket: {exc}") from exc

        self._client_socket = client_socket
        self._client_device = device
        self._connected_since = self._now()
        self.state = "connected"
        self._client_task = asyncio.create_task(self._serve_client(client_socket, device))
        self.logger.info("Bluetooth ELM327 client connected: %s", self._device_address(device))

    def request_disconnection(self, device: str) -> None:
        if self._loop is not None:
            self._loop.create_task(self.disconnect_client(device))

    def profile_released(self) -> None:
        self._registered = False
        self.state = "released"
        if self._loop is not None:
            self._loop.create_task(self.disconnect_client())

    def profile_cancelled(self) -> None:
        self.last_error = "BlueZ cancelled the pending profile request"

    def agent_released(self) -> None:
        self._agent_registered = False

    def note_pairing_event(self, device: Optional[str], message: str) -> None:
        address = self._device_address(device)
        self.last_pairing_event = f"{address}: {message}" if address else message
        self.logger.info("Bluetooth pairing event: %s", self.last_pairing_event)

    async def disconnect_client(self, device: Optional[str] = None) -> Dict[str, Any]:
        if device is not None and self._client_device not in {None, device}:
            return self.get_status()

        task = self._client_task
        client_socket = self._client_socket
        self._client_task = None
        self._client_socket = None
        self._client_device = None
        self._connected_since = None
        self._last_disconnected_at = self._now()

        if client_socket is not None:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client_socket.close()
            except OSError:
                pass

        current = asyncio.current_task()
        if task is not None and task is not current and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        if self._registered:
            self.state = "registered"
        elif self.state not in {"stopped", "error", "released"}:
            self.state = "stopped"
        return self.get_status()

    async def _serve_client(self, client_socket: socket.socket, device: str) -> None:
        loop = asyncio.get_running_loop()
        buffer = bytearray()
        previous_was_cr = False
        try:
            while True:
                data = await loop.sock_recv(client_socket, 1024)
                if not data:
                    break
                self.rx_bytes += len(data)

                for byte in data:
                    if byte in {10, 13}:
                        if byte == 10 and previous_was_cr:
                            previous_was_cr = False
                            continue
                        previous_was_cr = byte == 13
                        command = buffer.decode("ascii", errors="ignore").strip()
                        buffer.clear()
                        await self._handle_command(client_socket, command)
                        continue

                    previous_was_cr = False
                    if len(buffer) >= 4096:
                        buffer.clear()
                        await self._send(client_socket, "?\r>")
                        continue
                    buffer.append(byte)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError) as exc:
            self.logger.info("Bluetooth client disconnected: %s", exc)
        except Exception as exc:
            self.last_error = f"Bluetooth client error: {exc}"
            self.logger.exception(self.last_error)
        finally:
            if self._client_socket is client_socket:
                self._client_socket = None
                self._client_task = None
                self._client_device = None
                self._connected_since = None
                self._last_disconnected_at = self._now()
                if self._registered:
                    self.state = "registered"
            try:
                client_socket.close()
            except OSError:
                pass
            self.logger.info("Bluetooth ELM327 client session ended: %s", self._device_address(device))

    async def _handle_command(self, client_socket: socket.socket, command: str) -> None:
        if not command:
            if self._last_command is None:
                await self._send(client_socket, "?\r>")
                return
            command = self._last_command
        else:
            self._last_command = command

        echo_enabled = bool(self.echo_handler())
        result = await asyncio.to_thread(self.command_handler, command, "auto")
        response = str(result.get("response", ""))
        if not response.rstrip().endswith(">"):
            if response and not response.endswith(("\r", "\n")):
                response += "\r"
            response += ">"

        payload = f"{command}\r" if echo_enabled else ""
        payload += response
        await self._send(client_socket, payload)
        self.commands += 1

    async def _send(self, client_socket: socket.socket, payload: str) -> None:
        encoded = payload.encode("ascii", errors="ignore")
        await asyncio.get_running_loop().sock_sendall(client_socket, encoded)
        self.tx_bytes += len(encoded)

    def get_status(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,
            "registered": self._registered,
            "connected": self._client_socket is not None,
            "service_uuid": SPP_UUID,
            "profile_path": PROFILE_PATH,
            "config": asdict(self.config),
            "adapter": {
                "path": self._adapter_path,
                "name": self.config.adapter,
                "address": self._adapter_address,
                "alias": self._adapter_alias,
            },
            "client": {
                "device_path": self._client_device,
                "address": self._device_address(self._client_device),
                "connected_since": self._connected_since,
                "last_disconnected_at": self._last_disconnected_at,
            },
            "traffic": {
                "rx_bytes": self.rx_bytes,
                "tx_bytes": self.tx_bytes,
                "commands": self.commands,
                "last_command": self._last_command,
            },
            "agent_registered": self._agent_registered,
            "last_pairing_event": self.last_pairing_event,
            "warnings": list(self.warnings),
            "last_error": self.last_error,
        }
