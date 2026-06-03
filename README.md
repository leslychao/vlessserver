# Proxy Stack

Production-oriented Docker Compose stack for:

- `3x-ui` with a public HTTPS panel and a pinned wrapper image.
- One idempotently provisioned VLESS Reality inbound.
- `mtg` MTProto proxy kept on a separate port so VLESS can use `443`.
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

- `443/tcp` for VLESS Reality.
- `8443/tcp` for MTProto by default.
- `20530/tcp` for the public 3x-ui panel by default.

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
- `PUBLIC_HOST`: VPS IP or domain used in generated client links. Leave empty to auto-detect.
- `VLESS_PORT`: defaults to `443`.
- `MTG_BIND_PORT`: defaults to `8443` to avoid the VLESS port.
- `MTG_SECRET`: generated MTProto secret.

The generated VLESS link is written on the server to:

```text
/opt/proxy-stack/data/output/vless-reality.txt
```

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

## GitHub Actions deploy

Add these GitHub repository secrets:

- `DEPLOY_HOST`: VPS hostname or IP.
- `DEPLOY_USER`: SSH user. Use `root` or a user with passwordless `sudo`.
- `DEPLOY_SSH_KEY`: private SSH key for the deploy user. Preferred for production.
- `DEPLOY_PASSWORD`: optional password fallback when no SSH key is configured.
- `DEPLOY_PORT`: optional SSH port, defaults to `22`.
- `PROXY_STACK_ENV`: full multiline contents of the server `.env`.

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
