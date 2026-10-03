# Daylight AI

A small FastAPI application with HTML/CSS registration, login, and a signed-in ideas dashboard. User accounts are stored in PostgreSQL when `DATABASE_URL` points to PostgreSQL; passwords are stored as bcrypt hashes, never as plain text. SQLite is the local-development default.

## Run locally

Requires Python 3.11 or newer.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SECRET_KEY = "local-only-change-this-secret"
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Create an account to reach the dashboard. To use PostgreSQL locally, set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL before starting Uvicorn. To enable fresh AI ideas, set `AI_API_KEY` to an OpenAI API key; `AI_MODEL` can select another chat-completions-compatible model. Without the key, the dashboard uses its built-in starter ideas. Generated ideas are shown immediately and are not saved to the database.

## AWS layout

- An Ubuntu EC2 instance runs FastAPI behind Nginx. The included systemd unit runs Uvicorn as an unprivileged `daylight` user, bound only to localhost.
- Use Amazon RDS for PostgreSQL. Keep the database private; its security group should allow TCP 5432 only from the EC2 instance's security group. Do not expose PostgreSQL to the internet.
- Allow inbound EC2 traffic on 80 and 443. Restrict SSH (22) to your own IP. Add TLS with a certificate for your domain before accepting real accounts.
- Keep `SECRET_KEY`, the database URL/password, and `AI_API_KEY` in the server environment file, not in source control or browser code. Set `COOKIE_HTTPS_ONLY=true` once HTTPS is active.

## Deploy on Ubuntu EC2

1. Create an Ubuntu EC2 instance and an RDS PostgreSQL database. Configure the RDS security group to accept 5432 only from the EC2 security group. Note the RDS endpoint, database name, username, and password.
2. Connect to the instance and install the runtime packages:

   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip nginx
   sudo useradd --system --create-home --shell /usr/sbin/nologin daylight
   sudo mkdir -p /opt/daylight /etc/daylight
   ```

3. Copy the project files to `/opt/daylight` (for example with `scp`), then install the app into its own virtual environment:

   ```bash
   sudo chown -R daylight:daylight /opt/daylight
   sudo -u daylight python3 -m venv /opt/daylight/.venv
   sudo -u daylight /opt/daylight/.venv/bin/pip install -r /opt/daylight/requirements.txt
   ```

4. Create `/etc/daylight/daylight.env` with these values. URL-encode special characters in the database password before placing it in `DATABASE_URL`.

   ```dotenv
   DATABASE_URL=postgresql+psycopg://APP_USER:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/DATABASE_NAME
   SECRET_KEY=REPLACE_WITH_A_LONG_RANDOM_SECRET
   COOKIE_HTTPS_ONLY=true
   AI_API_KEY=
   AI_MODEL=gpt-4o-mini
   ```

   Generate a secret with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Protect the file so only root and the application group can read it:

   ```bash
   sudo chown root:daylight /etc/daylight/daylight.env
   sudo chmod 640 /etc/daylight/daylight.env
   ```

5. Install and start the app service and Nginx:

   ```bash
   sudo cp /opt/daylight/deploy/daylight.service /etc/systemd/system/daylight.service
   sudo cp /opt/daylight/deploy/nginx-daylight.conf /etc/nginx/sites-available/daylight
   sudo ln -s /etc/nginx/sites-available/daylight /etc/nginx/sites-enabled/daylight
   sudo nginx -t
   sudo systemctl daemon-reload
   sudo systemctl enable --now daylight nginx
   ```

   Set `server_name` in the Nginx config to your domain, and remove the default Nginx site if it conflicts. Use Certbot or your preferred certificate manager to configure HTTPS and redirect HTTP to HTTPS. Keep `COOKIE_HTTPS_ONLY=true` only when requests use HTTPS.

The app creates the `users` table at startup. For future schema changes, add and run database migrations rather than relying on `create_all` to alter existing tables.

## Tests

```bash
python -m unittest discover -s tests -v
```