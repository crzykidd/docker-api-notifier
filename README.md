
# docker-api-notifier

**docker-api-notifier** is a lightweight, extensible Python service that listens for Docker container events (e.g., container start) and triggers notification logic based on container labels.

This came out of a problem I was trying to solve. When a container starts up on a host I want it to auto register itself in my DNS server as a CNAME record to the docker host it was running on.

The first notifier I have written is for Technitium DNS server. I will look at adding some other things, like Pi-hole support, as well as additional.

Fair warning some of this was written with ChatGPT.

---

## Features

- Watches for Docker `start` events in real-time
- Parses container labels to determine notification actions
- Ships with Technitium DNS notifier for automatic CNAME registration
- Supports modular notifiers (e.g., DNS, dashboard, etc.)
- Runs as a container
- Easily configurable via environment variables

---

## Getting Started

### Run with Docker Compose

```yaml
services:
  docker-api-notifier:
    image: crzykidd/docker-api-notifier:latest
    container_name: docker-api-notifier
    environment:
      - DNS_SERVER_TYPE=Technitium
      - DNS_SERVER_URL=${DNS_SERVER_URL}
      - DNS_SERVER_API_TOKEN=${DNS_SERVER_API_TOKEN}
      - TZ=America/Los_Angeles
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/hostname:/etc/host_hostname:ro
    restart: unless-stopped
````

---

## ⚙️ Configuration

| Variable                    | Required | Description                                              |
| --------------------------- | -------- | -------------------------------------------------------- |
| `DNS_SERVER_TYPE`           | ✅        | DNS backend type (`Technitium` supported)                |
| `DNS_SERVER_URL`            | ✅        | URL of your Technitium DNS API endpoint                  |
| `DNS_SERVER_API_TOKEN`      | ✅        | API token for Technitium DNS                             |
| `SERVICE_TRACKER_URL`       | ⬜        | Service Tracker Dashboard API URL                        |
| `SERVICE_TRACKER_API_TOKEN` | ⬜        | Bearer token used to authenticate with the dashboard API |
| `TZ`                        | ⬜        | Optional timezone for logs (e.g. `America/Los_Angeles`)  |

Example DNS\_SERVER\_URL:

```bash
DNS_SERVER_URL="http://dns01.domain.com:5380/api/zones/records/add"
```

---

## Container Labels

To trigger `docker-api-notifier`, label your containers with:

```yaml
labels:
  dockernotifier.notifiers: "dns"
  dockernotifier.containerhostname: "testapp"
  dockernotifier.containerzone: "home.arpa"
  dockernotifier.dockerdomain: "home.arpa"
  dockernotifier.std.internalurl: "http://nginx:80"
  dockernotifier.std.externalurl: "https://nginx.example.com"
```

> The `dockernotifier.notifiers` label is required. If missing or empty, the container will be ignored.

* `dns` triggers DNS CNAME registration.
* `service-tracker-dashboard` triggers a POST to your internal service dashboard.

---

## 🔔 Service Tracker Dashboard Notifier

To enable the service tracker integration, include `service-tracker-dashboard` in your notifier list:

```yaml
labels:
  dockernotifier.notifiers: "service-tracker-dashboard"
  dockernotifier.std.internalurl: "http://nginx:80"           # optional
  dockernotifier.std.externalurl: "https://nginx.example.com" # optional
```

The notifier sends a JSON payload to your dashboard API with:

* `container_name` (required)
* `host` (required)
* `container_id` (optional)
* `internalurl` (optional)
* `externalurl` (optional)
* `stack_name` (optional — extracted from Docker labels)

You must also set these environment variables:

```yaml
environment:
  - SERVICE_TRACKER_URL=http://tracker.local:8080
  - SERVICE_TRACKER_API_TOKEN=your-secret-token
```

If either variable is missing, the notifier will skip execution and log:

```
[INFO] Not enabling Service Tracker Dashboard integration — missing SERVICE_TRACKER_URL or SERVICE_TRACKER_API_TOKEN
```

---

## Extending with Notifiers

New notifiers can be added to the `notifiers/` directory. Each notifier should expose a `register()` function that takes the required context and performs the custom action (e.g., DNS, webhook, dashboard post).

---

## Development

Install locally for development:

```bash
pip install -r requirements.txt
python main.py
```

---

## Roadmap

* ✅ Real-time event stream
* ✅ Technitium DNS CNAME support
* ✅ Service Tracker Dashboard integration
* 🔜 Support for other DNS providers (Pi-hole)
* 🔜 Discord or other message apps
* 🔜 Graceful cleanup / TTL retraction

---

## License

GNU GENERAL PUBLIC LICENSE. See [LICENSE](./LICENSE) for details.

---

## Feedback & Contributions

Open issues and PRs are welcome — especially for new notifier plugins!
