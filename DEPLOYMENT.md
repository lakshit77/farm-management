# Deploy Showground Live Monitoring API on AWS EC2

This guide covers deploying the **Showground Live Monitoring API** on an AWS EC2 instance using Docker, and exposing it so you can call it from **n8n** (or any HTTP client).

---

## Table of contents

1. [Prerequisites](#prerequisites)
2. [EC2 instance setup](#ec2-instance-setup)
3. [Install Docker on EC2](#install-docker-on-ec2)
4. [Deploy the API with Docker](#deploy-the-api-with-docker)
5. [Expose the API for n8n](#expose-the-api-for-n8n)
6. [Calling the API from n8n](#calling-the-api-from-n8n)
7. [Database migrations (Alembic)](#database-migrations-alembic)
8. [Optional: run on boot with systemd](#optional-run-on-boot-with-systemd)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- An AWS account and basic familiarity with EC2.
- Your project code in a Git repository (e.g. GitHub), or a way to copy the project onto the EC2 instance.
- A PostgreSQL database (e.g. Supabase or RDS) and its connection string.
- Wellington API credentials (customer ID, farm name, username, password) for the app.

---

## EC2 instance setup

1. **Launch an EC2 instance**
   - **AMI**: Amazon Linux 2023 or Ubuntu 22.04 LTS.
   - **Instance type**: e.g. `t3.micro` or `t3.small` (enough for this API).
   - **Key pair**: Create or select an SSH key pair and download the `.pem` file.
   - **Storage**: 8–20 GB is usually sufficient.

2. **Security group (inbound rules)**
   - **SSH (22)** – Your IP only (for administration).
   - **Custom TCP 8000** – Depending on who should call the API:
     - **Only n8n / your automation**: Restrict to the IP of the server running n8n (or your VPN/office IP).
     - **Any client (e.g. n8n on the internet)**: `0.0.0.0/0` (less secure; prefer restricting by IP if possible).

   Example:

   | Type        | Port | Source        | Description   |
   |------------|------|---------------|---------------|
   | SSH        | 22   | My IP         | SSH access    |
   | Custom TCP | 8000 | n8n server IP or 0.0.0.0/0 | API for n8n |

3. **Elastic IP (recommended)**  
   Allocate an Elastic IP and associate it with the instance so the public IP (and thus the API base URL) does not change after restarts.

4. **Connect via SSH**
   ```bash
   ssh -i /path/to/your-key.pem ec2-user@<EC2_PUBLIC_IP>   # Amazon Linux
   # or
   ssh -i /path/to/your-key.pem ubuntu@<EC2_PUBLIC_IP>     # Ubuntu
   ```

---

## Install Docker on EC2

### Amazon Linux 2023

```bash
sudo dnf update -y
sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
# Log out and back in (or new SSH session) so group membership applies
```

### Ubuntu 22.04

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
# Log out and back in (or new SSH session)
```

Verify:

```bash
docker --version
docker compose version
```

---

## Deploy the API with Docker

1. **Clone the repository** (or upload the project) on the EC2 instance:
   ```bash
   cd ~
   git clone <YOUR_REPO_URL> showgroundlive_monitoring
   cd showgroundlive_monitoring
   ```

2. **Create `.env` on the server**  
   Do **not** commit real secrets to Git. Create `.env` in the project root with the same variables your app expects (see `app/core/config.py`):

   ```env
   # Database (e.g. Supabase or RDS)
   DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE

   # Wellington / n8n
   WELLINGTON_API_BASE_URL=https://sglapi.wellingtoninternational.com
   WELLINGTON_CUSTOMER_ID=your_customer_id
   WELLINGTON_FARM_NAME=Your Farm Name
   WELLINGTON_USERNAME=your_username
   WELLINGTON_PASSWORD=your_password

   # Optional
   LOG_LEVEL=INFO
   LOG_DIR=logs
   ```

3. **Build and run with Docker Compose**
   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```

4. **Check that the API is running**
   ```bash
   docker compose ps
   curl http://localhost:8000/api/v1/hello/
   ```
   You should see something like: `{"message":"Hello, world!"}`.

---

## Expose the API for n8n

- The API is served by the container on **port 8000** and mapped to the host in `docker-compose.yml`.
- From outside the EC2 instance, use the **public IP** (or Elastic IP) of the instance.

**Base URL for n8n (and other clients):**

```text
http://<EC2_PUBLIC_IP>:8000
```

**Important:** If n8n runs on another machine (or in the cloud), ensure the EC2 security group allows inbound traffic on port **8000** from that machine’s IP (or from the range you use for automation). See [EC2 instance setup](#ec2-instance-setup).

For production over the internet, consider putting the app behind **HTTPS** (e.g. Nginx + Let’s Encrypt) and restricting access by IP or API key; the steps above focus on getting the API reachable for n8n.

---

## Calling the API from n8n

All API routes are under the prefix **`/api/v1`**. Responses follow the standard format: `{ "status": 1, "message": "success", "data": ... }`.

### Base URL in n8n

- **Base URL**: `http://<EC2_PUBLIC_IP>:8000`  
  (Replace `<EC2_PUBLIC_IP>` with your instance’s public or Elastic IP.)

### Endpoints you can call from n8n

| Purpose              | Method | URL (append to base URL)           | Notes |
|----------------------|--------|------------------------------------|-------|
| Health / test        | GET    | `/api/v1/hello/`                   | Returns `{"message":"Hello, world!"}`. |
| Daily schedule (Flow 1) | GET | `/api/v1/schedule/daily`           | Optional query: `?date=YYYY-MM-DD` (UTC). |
| Class monitoring (Flow 2) | GET | `/api/v1/schedule/class-monitor`   | No query params. |
| Schedule view        | GET    | `/api/v1/schedule/view`            | Optional: `?date=YYYY-MM-DD`. |

### Example: n8n HTTP Request node

1. Add an **HTTP Request** node.
2. **Method**: `GET`.
3. **URL**:  
   - Daily schedule: `http://<EC2_PUBLIC_IP>:8000/api/v1/schedule/daily`  
   - Class monitor: `http://<EC2_PUBLIC_IP>:8000/api/v1/schedule/class-monitor`  
   - Schedule view: `http://<EC2_PUBLIC_IP>:8000/api/v1/schedule/view?date=2025-02-17`
4. No authentication is required by default (add headers or auth in n8n if you add them to the API later).

### Example response (daily schedule)

```json
{
  "status": 1,
  "message": "success",
  "data": {
    "summary": "...",
    ...
  }
}
```

Use `data` in subsequent n8n nodes (e.g. for Telegram or other workflows).

---

## Database migrations (Alembic)

If you use Alembic and need to run migrations on the **host** (using the same `.env` as the container):

```bash
# On EC2, in project root, with .env present
pip install -r requirements.txt   # or use a venv
alembic upgrade head
```

To run migrations **inside** the running API container (one-off):

```bash
docker compose exec api alembic upgrade head
```

If your image does not include Alembic or the app’s Python env, run migrations from the host or from a dedicated migration job; the important part is that `DATABASE_URL` in `.env` points to the same database the API uses.

---

## Optional: run on boot with systemd

To start the stack automatically when the EC2 instance boots, you can use a systemd unit that runs `docker compose up -d` in the project directory.

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/showgroundlive-api.service
   ```

2. Paste (adjust `User`, `WorkingDirectory`, and path to `docker compose` if needed):

   ```ini
   [Unit]
   Description=Showground Live Monitoring API (Docker Compose)
   After=docker.service network-online.target
   Wants=network-online.target

   [Service]
   Type=oneshot
   RemainAfterExit=yes
   User=ec2-user
   WorkingDirectory=/home/ec2-user/showgroundlive_monitoring
   ExecStart=/usr/bin/docker compose up -d
   ExecStop=/usr/bin/docker compose down
   TimeoutStartSec=0

   [Install]
   WantedBy=multi-user.target
   ```

   On Ubuntu, use `ubuntu` instead of `ec2-user` and set `WorkingDirectory` to the path where you cloned the repo.

3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable showgroundlive-api
   sudo systemctl start showgroundlive-api
   ```

After a reboot, the API container should come up automatically.

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| **Cannot reach API from n8n** | Security group allows inbound **8000** from n8n’s IP (or your test client). EC2 firewall (e.g. `firewalld`) allows 8000 if enabled. |
| **Connection refused on EC2** | `docker compose ps` shows the container running. `curl http://localhost:8000/api/v1/hello/` works from the EC2 host. |
| **502 / empty response** | Container might be starting or crashing. Run `docker compose logs -f api` and check `DATABASE_URL` and Wellington credentials in `.env`. |
| **Database connection errors** | `DATABASE_URL` must be reachable from EC2 (Supabase/RDS security groups and VPC). Use `postgresql+asyncpg://...` for async driver. |
| **Container exits immediately** | Check `docker compose logs api`. Often due to missing or invalid `.env` (e.g. `DATABASE_URL`, Wellington credentials). |

Useful commands:

```bash
docker compose logs -f api    # Follow API logs
docker compose ps             # Container status
docker compose restart api    # Restart API only
docker compose down && docker compose up -d   # Full restart
```

---

## Summary

- **Docker**: Build and run with `docker compose up -d` after creating `.env`.
- **API base URL**: `http://<EC2_PUBLIC_IP>:8000`.
- **n8n**: Use **HTTP Request** with `GET` and URLs like `/api/v1/schedule/daily` or `/api/v1/schedule/class-monitor`.
- **Security**: Prefer restricting port 8000 to the n8n server IP; use HTTPS and stronger auth for production.
