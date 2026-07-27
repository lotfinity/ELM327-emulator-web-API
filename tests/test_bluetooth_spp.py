import asyncio
import socket
import unittest

from app.bluetooth_spp import BluetoothSPPTransport


class BluetoothSPPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        def command_handler(command, protocol):
            self.calls.append((command, protocol))
            return {"response": "OK\r>"}

        self.transport = BluetoothSPPTransport(
            command_handler=command_handler,
            echo_handler=lambda: True,
        )
        self.server, self.client = socket.socketpair()
        self.server.setblocking(False)
        self.client.setblocking(False)
        self.transport._client_socket = self.server
        self.transport._client_device = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        self.transport.state = "connected"
        self.task = asyncio.create_task(
            self.transport._serve_client(self.server, self.transport._client_device)
        )

    async def asyncTearDown(self):
        try:
            self.client.close()
        finally:
            if not self.task.done():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def read_prompts(self, count=1):
        loop = asyncio.get_running_loop()
        payload = b""
        while payload.count(b">") < count:
            payload += await asyncio.wait_for(loop.sock_recv(self.client, 1024), timeout=1)
        return payload

    async def test_crlf_is_one_command_and_echoes(self):
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self.client, b"ATI\r\n")
        payload = await self.read_prompts()
        self.assertEqual(payload, b"ATI\rOK\r>")
        self.assertEqual(self.calls, [("ATI", "auto")])

    async def test_blank_command_repeats_previous_command(self):
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self.client, b"ATZ\r\r")
        payload = await self.read_prompts(2)
        self.assertEqual(payload.count(b"ATZ\rOK\r>"), 2)
        self.assertEqual(self.calls, [("ATZ", "auto"), ("ATZ", "auto")])

    async def test_echo_can_be_disabled(self):
        self.transport.echo_handler = lambda: False
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(self.client, b"010C\r")
        payload = await self.read_prompts()
        self.assertEqual(payload, b"OK\r>")
        self.assertEqual(self.transport.commands, 1)
        self.assertEqual(self.calls, [("010C", "auto")])

    def test_bluez_device_path_is_converted_to_address(self):
        self.assertEqual(
            self.transport._device_address("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"),
            "AA:BB:CC:DD:EE:FF",
        )


if __name__ == "__main__":
    unittest.main()
