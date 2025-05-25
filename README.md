# docker-api-notifier

**docker-api-notifier** is a lightweight, extensible Python service that listens for Docker container events (e.g., container start) and triggers notification logic based on container labels.

This came out of a problem I was trying to solve.   When a container starts up on a host I want it to auto register itself in my dns server as a cname record to the docker host it was running on.   

The first notifier I have written is for Technitium DNS server.  I will look at adding some other things, like pihole support, as well as additional.

Fair warning some of this was written with ChatGPT 

---

## Features

- Watches for Docker `start` events in real-time
- Parses container labels to determine notification actions
- Ships with Technitium DNS notifier for automatic CNAME registration
- Runs as a container
- Easily configurable via environment variables

---

## Getting Started

### Run with Docker Compose

``` 
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
```
---

## ⚙️ Configuration

| Variable               | Required | Description                                                             |
|------------------------|----------|-------------------------------------------------------------------------|
| `DNS_SERVER_TYPE`      | ✅       | DNS backend type (`Technitium` supported)                               |
| `DNS_SERVER_URL`       | ✅       | URL of your Technitium DNS API endpoint                                 |
| `DNS_SERVER_API_TOKEN` | ✅       | API token for Technitium DNS                                            |
| `TZ`                   | ⬜️        | Optional timezone for logs (e.g. `America/Los_Angeles`)                 |


Example DNS_SERVER_URL
DNS_SERVER_URL="http://dns01.domain.com:5380/api/zones/records/add"

---

## Container Labels

To trigger `docker-api-notifier`, label your containers with:

```yaml
labels:
  dockernotifier.enable: "true" # if set is enabled.
  dockernotifier.containerhostname: "testapp" # what host name you want to container to be set as
  dockernotifier.containerzone: "home.arpa"  # The zone or domain name to update and set for the container host.
  dockernotifier.dockerdomain: "home.arpa" # the domain name to append to the dockerhost name to use as the CNAME entry
```

> These labels tell the notifier to register `testapp.home.arpa` as a CNAME pointing to `dockerhost.home.arpa`.

---


## Extending with Notifiers

New notifiers can be added to the `notifiers/` directory. Each notifier should expose a `register()` function that takes the required context and performs the custom action (e.g., DNS, webhook, etc.).

---

## Development

Install locally for development:

```bash
pip install -r requirements.txt
python main.py
```

---

## Roadmap

- ✅ Real-time event stream
- ✅ Technitium DNS CNAME support
- 🔜 Support for other DNS providers (Pi-hole)
- 🔜 Discord or other message apps
- 🔜 Graceful cleanup / TTL retraction

---

## License

GNU GENERAL PUBLIC LICENSE. See [LICENSE](./LICENSE) for details.

---

## Feedback & Contributions

Open issues and PRs are welcome — especially for new notifier plugins!
