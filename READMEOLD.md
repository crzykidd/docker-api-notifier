# 🚀 Docker API Notifier

![Docker Image](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![Python](https://img.shields.io/badge/python-3.11-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

A lightweight, event-driven Docker monitor that automatically updates DNS entries and service dashboards based on container events and metadata. 

I started this project to solve updating my Technitium DNS server when a host started up on a docker host.   So that is the first task this container does.  

Then as I was working I was struggling with how to update my dashboard via API etc.  So I decided to write a self defining dashboard.   So this notifier also can be enabled to send updates to [STD-Service Tracker Dashboard](https://github.com/crzykidd/service-tracker-dashboard).   

While STD has a small config file and some manual setting options.  The real design was to specify tags in docker compose so that your config would define and update the dashboard.  

---

## 📚 Table of Contents

1. [What It Does](#1-what-it-does)
2. [Environment Variables](#2-environment-variables)
3. [Labels You Can Use](#3-labels-you-can-use)
4. [Docker Compose Example](#4-docker-compose-example)
5. [Building Locally](#5-building-locally)

---

## 1. What It Does

`docker-api-notifier` listens for Docker events (start, stop, die, etc.) and sends updates to external systems.

Supported integrations:
- 🧭 **Technitium DNS** – updates DNS records.
- 📊 **Service Tracker Dashboard** – sends metadata and health checks.

---

## 2. Environment Variables

### 🛠 General

| Variable               | Required | Default | Description |
|------------------------|----------|---------|-------------|
| TZ                   | No       | `UTC`   | Timezone for logging. |

### 🌐 DNS (Technitium)

| Variable               | Required | Description |
|------------------------|----------|-------------|
| DNS_SERVER_URL       | ✅ Yes   | URL to your DNS API. |
| DNS_SERVER_API_TOKEN | ✅ Yes   | Auth token for DNS server. |
| DNS_SERVER_TYPE      | No       | Optional descriptor. |

### 📊 Service Tracker Dashboard

| Variable           | Required | Description |
|--------------------|----------|-------------|
| STD_URL          | ✅ Yes   | Dashboard API endpoint. |
| STD_API_TOKEN    | ✅ Yes   | API token for dashboard. |
| STD_LOG_TO_STDOUT| No       | Set to `0` to disable console logs. |
| STD_REFRESH_SECONDS  | No       | `300` Interval in seconds to check container state and update API |

---

## 3. Labels You Can Use

Add labels to your containers to control what happens when they're started or updated.

### 🔧 Required for Activation

| Label                         | Required | Description |
|------------------------------|----------|-------------|
| dockernotifier.notifiers   | ✅ Yes   | List of notifiers to run, e.g. `dns,service-tracker-dashboard`. |

### 🌐 DNS Labels

| Label                                  | Required | Description |
|----------------------------------------|----------|-------------|
| dockernotifier.dns.containerhostname | ✅ Yes for DNS | Hostname (e.g., `sonarr`). |
| dockernotifier.dns.containerzone     | ✅ Yes for DNS  | Zone/domain (e.g., `home.local`). |
| dockernotifier.dns.dockerdomain      | ✅ Yes for DNS  | Docker host domain (e.g., `docker`). |

### 📊 Service Tracker Labels

| Label                                   | Required | Description |
|----------------------------------------|----------|-------------|
| dockernotifier.std.internalurl       | No       | Internal service URL. |
| dockernotifier.std.externalurl       | No       | Public URL. |
| dockernotifier.std.internal.health   | No       | Internal health check. |
| dockernotifier.std.external.health   | No       | External health check. |
| dockernotifier.std.group             | No       | Group name for dashboard. |
| dockernotifier.std.icon              | No       | Icon file name (e.g. `sonarr.svg`)|

---

## 4. Docker Compose Example

```yaml
services:
  docker-api-notifier:
    build: .
    container_name: docker-api-notifier
    environment:
      - DNS_SERVER_TYPE=Technitium
      - DNS_SERVER_URL=http://dns.example.com:5380/api/zones/records/add
      - DNS_SERVER_API_TOKEN=TOKENFROMDNSSERVER
      - STD_URL=http://std.example.com:8815
      - STD_API_TOKEN=TOKENFROMSTDSERVER
      - TZ=America/Los_Angeles
      - STD_REFRESH_SECONDS=300 
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/hostname:/etc/host_hostname:ro
      - /var/docker/docker-api-notifier:/config
    restart: unless-stopped
