# Porla setup (Ubuntu 22.04, v0.41.0, basic auth)

## 1) Determine architecture
```bash
uname -m
```
Map arch -> asset:
- `x86_64` -> `amd64`
- `aarch64` -> `arm64`

From the release page, copy the exact Linux asset filename for your arch (e.g., `porla_linux_amd64.tar.gz`).

## 2) Create Porla system user + dirs
```bash
sudo id -u porla >/dev/null 2>&1 || sudo useradd --system --home /var/lib/porla --shell /usr/sbin/nologin porla
sudo mkdir -p /var/lib/porla/{config,data,watch}
sudo chown -R porla:porla /var/lib/porla
```

## 3) Download + install Porla v0.41.0
```bash
# PORLA_VERSION=0.41.0
# PORLA_ASSET="REPLACE_WITH_REAL_FILENAME"
# curl -L -o /tmp/porla.tgz "https://github.com/porla/porla/releases/download/v${PORLA_VERSION}/${PORLA_ASSET}"
# sudo tar -xzf /tmp/porla.tgz -C /usr/local/bin
sudo curl  -L -o /usr/local/bin/porla "https://github.com/porla/porla/releases/download/v0.41.0/porla-linux-amd64"
sudo chmod +x /usr/local/bin/porla

```

## 4) Configure Porla basic auth
Set Porla API bind address to `127.0.0.1:1337` and enable basic auth.

If Porla uses a config file, place it under `/var/lib/porla/config/` and update `deploy/systemd/porla.service` `ExecStart` to point at it. If it supports env vars, populate `/etc/porla/porla.env` and keep the `EnvironmentFile` line in the unit.

## 5) Install the systemd unit
```bash
make install-porla-systemd
```
If you want Porla to run as the `porla` user, add `User=porla` and `Group=porla` to `deploy/systemd/porla.service` before installing.

## 6) Wire ttseed to Porla
Update `config.yaml`:
```yaml
porla:
  base_url: "http://127.0.0.1:1337"
  auth:
    type: "basic"
    username: "YOUR_USER"
    password: "YOUR_PASS"
```

## 7) Quick health check
```bash
curl -f http://127.0.0.1:1337/api/v1/health
```
