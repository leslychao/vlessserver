# Proxy Stack

Production-oriented Docker Compose stack for:

- `3x-ui` with a public HTTPS panel and a pinned wrapper image.
- One idempotently provisioned VLESS Reality inbound on a configurable direct TCP port.
- `mtg` MTProto proxy kept on a separate port from VLESS.
- GitHub Actions SSH deploy to `/opt/proxy-stack/app` with persistent data in `/opt/proxy-stack/data`.

## Server prerequisites

GitHub Actions bootstraps Docker Engine and the Docker Compose plugin automatically when they are missing. The deploy user must be `root` or have passwordless `sudo`.

For manual setup, Docker can also be installed with:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Open the required firewall ports:

- `10443/tcp` for VLESS Reality by default.
- `8443/tcp` for MTProto by default.
- `20530/tcp` for the public 3x-ui panel by default.

GitHub Actions configures supported host firewalls automatically during deploy. It opens the SSH port, `VLESS_PORT`, `MTG_BIND_PORT`, and `XUI_PANEL_PORT` when `FIREWALL_AUTO_CONFIG=true`. Supported host firewalls are active `ufw`, active `firewalld`, and direct `iptables` rules when no managed firewall is active.

The workflow does not enable a disabled firewall, and it cannot configure provider-side cloud firewalls. If the VPS provider has a separate network firewall, allow the same TCP ports there.

If this server sits behind a home or office router, forward the VLESS Reality port directly to this host:

```text
WAN 10443/tcp -> LAN_IP_OF_THIS_SERVER:10443/tcp
```

Do not point this VLESS Reality inbound through an HTTPS reverse proxy. Reality/TCP expects a direct TCP connection to Xray. Keeping router port `443` forwarded to another local server is fine as long as the client link uses `10443`.

When `ADDITIONAL_PUBLIC_IPS` is set, GitHub Actions assigns those IPv4 addresses as `/32` addresses on the server default IPv4 interface and installs a `proxy-stack-public-ips.service` systemd oneshot to reapply them after reboot. The primary `PUBLIC_HOST` address is not reassigned because it should already be configured by the provider or OS.

## Environment

Create a server-local `.env` from `.env.example` and replace every placeholder secret.

Recommended secret generation:

```bash
openssl rand -base64 36
docker run --rm ghcr.io/9seconds/mtg:2.2.4 generate-secret --hex cloudflare.com
```

Important variables:

- `XUI_ADMIN_PASSWORD`: long random panel password.
- `XUI_PANEL_WEB_BASE_PATH`: non-root hidden panel path, for example `/admin-8f2d6c1a/`.
- `PUBLIC_HOST`: primary VPS IP or domain used in the first generated VLESS link. Leave empty to auto-detect.
- `ADDITIONAL_PUBLIC_IPS`: comma-separated secondary public IPv4 addresses. These are assigned to the VPS interface and get additional generated VLESS links.
- `XRAY_OUTBOUND_SEND_THROUGH`: defaults to `origin`, so Xray outbound traffic uses the local IP that accepted the inbound connection.
- `VLESS_PORT`: defaults to `10443`. If an existing 3x-ui inbound with the same `VLESS_REMARK` was previously created on another port, the provisioner updates that inbound to this configured port and rewrites the generated client links.
- `MTG_BIND_PORT`: defaults to `8443` to avoid the VLESS port.
- `MTG_SECRET`: generated MTProto secret.
- `FIREWALL_AUTO_CONFIG`: defaults to `true`; opens required host firewall ports during deploy.
- `FIREWALL_OPEN_PANEL_PORT`: defaults to `true`; set to `false` only if the panel is not meant to be public.

The generated VLESS link is written on the server to:
If `ADDITIONAL_PUBLIC_IPS` contains multiple values, one VLESS link is written for `PUBLIC_HOST` plus one link per additional IP.

```text
/opt/proxy-stack/data/output/vless-reality.txt
```

The generated links should contain `:10443` unless `VLESS_PORT` is explicitly overridden.

## Manual deploy

```bash
docker compose --env-file .env config
docker compose --env-file .env pull mtg
docker compose --env-file .env build --pull xui xui-provision
docker compose --env-file .env up -d xui mtg
docker compose --env-file .env run --rm xui-provision
docker compose --env-file .env ps
```

The provisioner is idempotent. Running it again will not create another inbound with the same `VLESS_REMARK`.

Verify the configured ports and generated VLESS link on the server:

```bash
grep -E '^(VLESS_PORT|MTG_BIND_PORT)=' .env
sudo ss -ltnp | grep -E '[:.]10443[[:space:]]'
sudo ss -ltnp | grep -E '[:.]8443[[:space:]]'
sudo cat /opt/proxy-stack/data/output/vless-reality.txt
```

The VLESS client link should contain `@PUBLIC_HOST:10443`. If `PROXY_STACK_ENV` or the server `.env` still contains `VLESS_PORT=443`, update it to `VLESS_PORT=10443` and rerun the provisioner.

## GitHub Actions deploy

Add these GitHub repository secrets:

- `DEPLOY_HOST`: VPS hostname or IP.
- `DEPLOY_USER`: SSH user. Use `root` or a user with passwordless `sudo`.
- `DEPLOY_SSH_KEY`: private SSH key for the deploy user. Preferred for production.
- `DEPLOY_PASSWORD`: optional password fallback when no SSH key is configured.
- `DEPLOY_PORT`: optional SSH port, defaults to `22`.
- `PROXY_STACK_ENV`: full multiline contents of the server `.env`.

`PROXY_STACK_ENV` must include the full production stack environment, not only deploy credentials. At minimum it must contain `XUI_ADMIN_USERNAME`, `XUI_ADMIN_PASSWORD`, `MTG_SECRET`, `VLESS_REMARK`, and `VLESS_CLIENT_EMAIL`.

The workflow deploys on pushes to `main` and can also be run manually from the Actions tab.

## Access

Panel URL:

```text
https://SERVER_IP:20530/admin-8f2d6c1a/
```

If the stack generated a self-signed certificate, browsers and smoke checks must accept the certificate manually. Replace `XUI_PANEL_CERT_FILE` and `XUI_PANEL_KEY_FILE` with real certificate paths when a trusted certificate is available.

SSH tunnel alternative:

```bash
ssh -L 20530:127.0.0.1:20530 user@SERVER_IP
```

Then open:

```text
https://127.0.0.1:20530/admin-8f2d6c1a/
```

## Logs

```bash
docker logs xui --tail=100
docker logs mtg --tail=100
docker compose --env-file .env run --rm xui-provision
```

Custom stack scripts log in English and do not print the admin password.
