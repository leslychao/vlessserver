import unittest
from unittest.mock import patch

from provisioner.provision import sync_existing_inbound_port, tcp_port_env


class FakeXuiClient:
    def __init__(self, response_obj=None):
        self.calls = []
        self.response_obj = response_obj

    def api(self, method: str, path: str, data=None):
        self.calls.append((method, path, data))
        return {"success": True, "obj": self.response_obj if self.response_obj is not None else data}


class SyncExistingInboundPortTest(unittest.TestCase):
    def test_rejects_invalid_desired_port(self):
        client = FakeXuiClient()
        existing = {
            "id": 42,
            "remark": "vless-reality-main",
            "port": 443,
        }

        with self.assertRaises(SystemExit):
            sync_existing_inbound_port(client, existing, 70000)

        self.assertEqual(client.calls, [])

    def test_updates_existing_inbound_when_configured_port_changes(self):
        client = FakeXuiClient()
        existing = {
            "id": 42,
            "remark": "vless-reality-main",
            "port": 443,
            "protocol": "vless",
            "settings": "{}",
            "streamSettings": "{}",
        }

        updated = sync_existing_inbound_port(client, existing, 10443)

        self.assertEqual(updated["port"], 10443)
        self.assertEqual(existing["port"], 443)
        self.assertEqual(len(client.calls), 1)
        method, path, payload = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "inbounds/update/42")
        self.assertEqual(payload["port"], 10443)

    def test_leaves_existing_inbound_unchanged_when_port_already_matches(self):
        client = FakeXuiClient()
        existing = {
            "id": 42,
            "remark": "vless-reality-main",
            "port": 10443,
            "protocol": "vless",
            "settings": "{}",
            "streamSettings": "{}",
        }

        updated = sync_existing_inbound_port(client, existing, 10443)

        self.assertEqual(updated, existing)
        self.assertEqual(client.calls, [])


class TcpPortEnvTest(unittest.TestCase):
    def test_rejects_out_of_range_port_from_environment(self):
        with patch.dict("os.environ", {"VLESS_PORT": "0"}):
            with self.assertRaises(SystemExit):
                tcp_port_env("VLESS_PORT", 10443)

        with patch.dict("os.environ", {"VLESS_PORT": "70000"}):
            with self.assertRaises(SystemExit):
                tcp_port_env("VLESS_PORT", 10443)

    def test_returns_default_when_environment_value_is_empty(self):
        with patch.dict("os.environ", {"VLESS_PORT": ""}):
            self.assertEqual(tcp_port_env("VLESS_PORT", 10443), 10443)


if __name__ == "__main__":
    unittest.main()
