#!/usr/bin/env python3
import http.cookiejar
import json
import os
import secrets
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


DEFAULT_VLESS_PORT = 10443


def log(message: str) -> None:
    print(f"[xui-provision] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[xui-provision] ERROR: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        fail(f"Required environment variable {name} is not set")
    return value


def bool_env(name: str, default: bool = False) -> bool:
    value = env(name, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    value = env(name, str(default))
    if value == "":
        value = str(default)
    try:
        return int(value)
    except ValueError:
        fail(f"Environment variable {name} must be an integer")


def validate_tcp_port(name: str, value: int) -> int:
    if value < 1 or value > 65535:
        fail(f"Environment variable {name} must be a TCP port between 1 and 65535")
    return value


def tcp_port_env(name: str, default: int) -> int:
    return validate_tcp_port(name, int_env(name, default))


def normalize_base_path(value: str) -> str:
    value = value or "/"
    if not value.startswith("/"):
        value = "/" + value
    if not value.endswith("/"):
        value += "/"
    return value


class XuiClient:
    def __init__(self, base_url: str, username: str, password: str, insecure_tls: bool):
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        context = None
        if self.base_url.startswith("https://") and insecure_tls:
            context = ssl._create_unverified_context()
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=context),
        )

    def request(self, method: str, path: str, data=None, form=None, timeout: int = 10):
        url = urllib.parse.urljoin(self.base_url, path.lstrip("/"))
        body = None
        headers = {"Accept": "application/json"}
        if data is not None and form is not None:
            raise ValueError("Only one of data or form can be provided")
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def login(self) -> None:
        result = self.request(
            "POST",
            "login",
            {"username": self.username, "password": self.password},
            timeout=10,
        )
        if not isinstance(result, dict) or not result.get("success"):
            fail("Panel login failed. Check XUI_ADMIN_USERNAME, XUI_ADMIN_PASSWORD, and panel settings.")

    def api(self, method: str, path: str, data=None):
        result = self.request(method, f"panel/api/{path}", data=data, timeout=20)
        if isinstance(result, dict) and result.get("success") is False:
            fail(f"3x-ui API call failed at {path}: {result.get('msg', 'unknown error')}")
        return result

    def panel(self, method: str, path: str, data=None, form=None):
        result = self.request(method, path, data=data, form=form, timeout=20)
        if isinstance(result, dict) and result.get("success") is False:
            fail(f"3x-ui panel call failed at {path}: {result.get('msg', 'unknown error')}")
        return result


def wait_for_panel(client: XuiClient, attempts: int = 60) -> None:
    for attempt in range(1, attempts + 1):
        try:
            client.login()
            log("Panel login succeeded")
            return
        except SystemExit:
            raise
        except Exception as exc:
            if attempt == attempts:
                fail(f"Panel did not become ready: {exc}")
            log(f"Waiting for panel readiness ({attempt}/{attempts})")
            time.sleep(2)


def api_obj(response):
    if isinstance(response, dict):
        return response.get("obj")
    return None


def json_string(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_nested_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


def detect_public_host() -> str:
    configured = env("PUBLIC_HOST").strip()
    if configured:
        return configured

    for url in ("https://api4.ipify.org", "https://ipv4.icanhazip.com", "https://4.ident.me"):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                host = response.read().decode("utf-8").strip()
                if host:
                    return host
        except Exception:
            continue

    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        fail("Unable to detect PUBLIC_HOST. Set it explicitly in .env.")


def public_hosts() -> list[str]:
    hosts: list[str] = []
    configured = env("PUBLIC_HOST").strip()
    if configured:
        hosts.append(configured)
    else:
        hosts.append(detect_public_host())

    additional_ips = env("ADDITIONAL_PUBLIC_IPS").strip()
    if additional_ips:
        hosts.extend(item.strip() for item in additional_ips.split(",") if item.strip())

    unique_hosts: list[str] = []
    for host in hosts:
        if host not in unique_hosts:
            unique_hosts.append(host)

    return unique_hosts


def generate_link(public_host: str, inbound: dict, display_remark: str | None = None) -> str:
    settings = load_nested_json(inbound.get("settings"))
    stream = load_nested_json(inbound.get("streamSettings"))
    clients = settings.get("clients") or []
    if not clients:
        fail("Inbound has no clients, cannot generate a VLESS link")

    client = clients[0]
    reality = stream.get("realitySettings") or {}
    reality_settings = reality.get("settings") or {}
    server_names = reality.get("serverNames") or []
    short_ids = reality.get("shortIds") or []

    params = {
        "type": stream.get("network", "tcp"),
        "security": "reality",
        "encryption": settings.get("encryption", "none"),
        "pbk": reality_settings.get("publicKey", ""),
        "fp": reality_settings.get("fingerprint", "chrome"),
        "sni": (server_names[0] if server_names else reality_settings.get("serverName", "")),
        "sid": (short_ids[0] if short_ids else ""),
        "spx": reality_settings.get("spiderX", "/"),
    }

    flow = client.get("flow")
    if flow:
        params["flow"] = flow

    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    remark = urllib.parse.quote(display_remark or inbound.get("remark") or env("VLESS_REMARK", "vless-reality-main"))
    return f"vless://{client['id']}@{public_host}:{inbound['port']}?{query}#{remark}"


def write_output(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.write("\n")
    os.chmod(path, 0o600)


def find_existing_inbound(inbounds, remark: str):
    for inbound in inbounds:
        if inbound.get("remark") == remark:
            return inbound
    return None


def current_inbound_port(inbound: dict) -> int:
    try:
        return int(inbound.get("port", 0))
    except (TypeError, ValueError):
        fail(f"Existing inbound '{inbound.get('remark', '<unknown>')}' has an invalid port")


def sync_existing_inbound_port(client: XuiClient, inbound: dict, desired_port: int) -> dict:
    validate_tcp_port("VLESS_PORT", desired_port)
    current_port = current_inbound_port(inbound)
    if current_port == desired_port:
        log(f"Inbound '{inbound.get('remark', '<unknown>')}' already uses port {desired_port}")
        return inbound

    inbound_id = inbound.get("id")
    if inbound_id in (None, ""):
        fail(f"Existing inbound '{inbound.get('remark', '<unknown>')}' cannot be updated because it has no id")

    updated = dict(inbound)
    updated["port"] = desired_port
    log(f"Updating inbound '{updated.get('remark', '<unknown>')}' port from {current_port} to {desired_port}")
    response = client.api("POST", f"inbounds/update/{inbound_id}", updated)
    obj = api_obj(response)
    return obj if isinstance(obj, dict) else updated


def parse_panel_xray_response(response) -> tuple[dict, str]:
    obj = api_obj(response)
    if isinstance(obj, str):
        wrapper = json.loads(obj)
    elif isinstance(obj, dict):
        wrapper = obj
    else:
        fail("3x-ui returned an unexpected Xray settings response")

    xray_setting = wrapper.get("xraySetting")
    if isinstance(xray_setting, str):
        config = json.loads(xray_setting)
    elif isinstance(xray_setting, dict):
        config = xray_setting
    else:
        fail("3x-ui returned an unexpected xraySetting payload")

    outbound_test_url = wrapper.get("outboundTestUrl") or "https://www.google.com/generate_204"
    return config, outbound_test_url


def configure_origin_sendthrough(client: XuiClient) -> bool:
    send_through = env("XRAY_OUTBOUND_SEND_THROUGH", "origin").strip()
    if not send_through:
        log("Xray outbound sendThrough configuration disabled")
        return False

    response = client.panel("POST", "panel/xray/")
    config, outbound_test_url = parse_panel_xray_response(response)
    outbounds = config.setdefault("outbounds", [])
    if not isinstance(outbounds, list):
        fail("xrayTemplateConfig.outbounds must be an array")

    selected = None
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        if outbound.get("protocol") == "freedom" and outbound.get("tag") == "direct":
            selected = outbound
            break
        if selected is None and outbound.get("protocol") == "freedom":
            selected = outbound

    if selected is None:
        selected = {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {"domainStrategy": "AsIs", "redirect": "", "noises": []},
        }
        outbounds.insert(0, selected)

    if selected.get("sendThrough") == send_through:
        log(f"Xray outbound sendThrough already set to {send_through}")
        return False

    selected["sendThrough"] = send_through
    payload = json_string(config)
    client.panel(
        "POST",
        "panel/xray/update",
        form={"xraySetting": payload, "outboundTestUrl": outbound_test_url},
    )
    log(f"Xray outbound sendThrough set to {send_through}")
    return True


def main() -> None:
    username = required_env("XUI_ADMIN_USERNAME")
    password = required_env("XUI_ADMIN_PASSWORD")
    panel_port = int_env("XUI_PANEL_PORT", 20530)
    base_path = normalize_base_path(env("XUI_PANEL_WEB_BASE_PATH", "/admin/"))
    scheme = "https" if bool_env("XUI_PANEL_TLS_ENABLED", True) else "http"
    insecure_tls = bool_env("XUI_PANEL_INSECURE_TLS", True)
    client = XuiClient(f"{scheme}://127.0.0.1:{panel_port}{base_path}", username, password, insecure_tls)

    wait_for_panel(client)

    remark = env("VLESS_REMARK", "vless-reality-main")
    inbound_port = tcp_port_env("VLESS_PORT", DEFAULT_VLESS_PORT)
    hosts = public_hosts()
    output_file = env("PROVISION_OUTPUT_FILE", "/output/vless-reality.txt")

    xray_config_changed = configure_origin_sendthrough(client)

    list_response = client.api("GET", "inbounds/list")
    inbounds = api_obj(list_response) or []
    existing = find_existing_inbound(inbounds, remark)
    if existing:
        port_changed = current_inbound_port(existing) != inbound_port
        existing = sync_existing_inbound_port(client, existing, inbound_port)
        log(f"Inbound '{remark}' already exists; no duplicate will be created")
        links = [generate_link(host, existing, f"{remark}-{host}") for host in hosts]
        write_output(output_file, "\n".join(links))
        log(f"Connection link written to {output_file}")
        if xray_config_changed or port_changed:
            try:
                client.api("POST", "server/restartXrayService")
                log("Xray restart requested")
            except Exception as exc:
                log(f"Xray restart request failed; panel background job may restart it later: {exc}")
        return

    uuid_response = client.api("GET", "server/getNewUUID")
    key_response = client.api("GET", "server/getNewX25519Cert")
    client_uuid = (api_obj(uuid_response) or {}).get("uuid") or str(uuid.uuid4())
    key_pair = api_obj(key_response) or {}
    private_key = key_pair.get("privateKey")
    public_key = key_pair.get("publicKey")
    if not private_key or not public_key:
        fail("3x-ui did not return a Reality X25519 key pair")

    server_names = [item.strip() for item in env("VLESS_REALITY_SERVER_NAMES", "www.cloudflare.com").split(",") if item.strip()]
    if not server_names:
        fail("VLESS_REALITY_SERVER_NAMES must contain at least one server name")

    client_email = env("VLESS_CLIENT_EMAIL", "main-client")
    short_id = secrets.token_hex(4)
    sub_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]

    vless_settings = {
        "clients": [
            {
                "id": client_uuid,
                "flow": env("VLESS_CLIENT_FLOW", "xtls-rprx-vision"),
                "email": client_email,
                "limitIp": int_env("VLESS_CLIENT_LIMIT_IP", 0),
                "totalGB": int_env("VLESS_CLIENT_TOTAL_GB", 0),
                "expiryTime": 0,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "comment": "provisioned by proxy-stack",
                "reset": 0,
            }
        ],
        "decryption": "none",
        "encryption": "none",
        "fallbacks": [],
    }
    stream_settings = {
        "network": "tcp",
        "security": "reality",
        "externalProxy": [],
        "realitySettings": {
            "show": False,
            "xver": 0,
            "target": env("VLESS_REALITY_TARGET", "www.cloudflare.com:443"),
            "serverNames": server_names,
            "privateKey": private_key,
            "minClientVer": "",
            "maxClientVer": "",
            "maxTimediff": 0,
            "shortIds": [short_id],
            "mldsa65Seed": "",
            "settings": {
                "publicKey": public_key,
                "fingerprint": env("VLESS_REALITY_FINGERPRINT", "chrome"),
                "serverName": server_names[0],
                "spiderX": env("VLESS_REALITY_SPIDER_X", "/"),
                "mldsa65Verify": "",
            },
        },
        "tcpSettings": {
            "acceptProxyProtocol": False,
            "header": {"type": "none"},
        },
    }
    sniffing = {
        "enabled": True,
        "destOverride": ["http", "tls", "quic"],
        "metadataOnly": False,
        "routeOnly": False,
        "ipsExcluded": [],
        "domainsExcluded": [],
    }
    inbound = {
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": remark,
        "enable": True,
        "expiryTime": 0,
        "trafficReset": "never",
        "listen": "",
        "port": inbound_port,
        "protocol": "vless",
        "settings": json_string(vless_settings),
        "streamSettings": json_string(stream_settings),
        "tag": "",
        "sniffing": json_string(sniffing),
        "clientStats": [],
    }

    add_response = client.api("POST", "inbounds/add", inbound)
    created = api_obj(add_response) or inbound
    log(f"Inbound '{remark}' created on port {inbound_port}")

    try:
        client.api("POST", "server/restartXrayService")
        log("Xray restart requested")
    except Exception as exc:
        log(f"Xray restart request failed; panel background job may restart it later: {exc}")

    links = [generate_link(host, created, f"{remark}-{host}") for host in hosts]
    write_output(output_file, "\n".join(links))
    log(f"Connection link written to {output_file}")


if __name__ == "__main__":
    main()
