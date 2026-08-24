# Raspberry Pi project

This repository contains a small multi-language setup with Python and C examples, plus a simple HTML dashboard for sensor monitoring and reporting.

## Structure

- `src/python/hello.py` - Python hello example
- `src/c/hello.c` - C hello example
- `index.html` - main dashboard landing page
- `Makefile` - build and run helpers

## Commands

### Python and C

- `python3 src/python/hello.py`
- `make build-c`
- `make run-python`
- `make run-c`
- `make clean`

### Local web preview

Start the local dashboard server:

```bash
cd /home/jollyjae/repo/github/raspberrypi
python3 -m http.server 8000
```

Then open:

- `http://localhost:8000`

If it is not running yet, start it with the command above. If it is already running, reload the page in the browser.

### Stop, restart, or reset the server

Stop the current server:

```bash
pkill -f "python3 -m http.server 8000"
```

Restart it:

```bash
cd /home/jollyjae/repo/github/raspberrypi
python3 -m http.server 8000
```

Reset the local preview state:

```bash
pkill -f "python3 -m http.server 8000" || true
cd /home/jollyjae/repo/github/raspberrypi
python3 -m http.server 8000
```

This will fully restart the serving process and refresh the static page content.

### Map (Sensor locations)

The dashboard includes an interactive map on the main page that shows sensor locations.

- Open the main page at `http://localhost:8000` and scroll to the "Sensor Map" section.
- The map uses Leaflet + OpenStreetMap tiles (CDN). If you need an offline option, we'll add local tiles or a hosted tile provider.
- Add a marker client-side by entering a name, latitude, and longitude, then clicking `Add sensor`.

Notes:

- The current map code is client-only for a quick prototype; to persist sensor locations you'll need a small backend (e.g., Flask or a simple JSON file API).
- If your Raspberry Pi is running the server and you want remote access, ensure proper firewall/port forwarding and authentication.

### Authentication and admin

The API now supports token-based authentication for admin operations. By default the admin credentials are:

- username: `admin`
- password: `password`

You can change these by exporting env vars before running the server:

```bash
export RPM_ADMIN_USER=youruser
export RPM_ADMIN_PASS=yourpass
export RPM_SECRET=some-long-secret
```

Obtain a token (example using curl):

```bash
curl -sS -X POST -H "Content-Type: application/json" -d '{"username":"admin","password":"password"}' http://localhost:5000/api/auth
```

The `admin.html` interface will request a token when you log in and store it in your browser's `localStorage` to authorize delete operations.

### Deploy: systemd unit (example)

Here is an example `systemd` unit file you can use on the Raspberry Pi to run the API with `gunicorn`:

Create `/etc/systemd/system/raspberrypi.service` with:

```ini
[Unit]
Description=Raspberry Pi Sensor API
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/repo/github/raspberrypi
Environment=RPM_ADMIN_USER=admin
Environment=RPM_ADMIN_PASS=password
Environment=RPM_SECRET=change-me
ExecStart=/home/pi/repo/github/raspberrypi/.venv/bin/gunicorn -w 3 -b 0.0.0.0:5000 server.app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable raspberrypi.service
sudo systemctl start raspberrypi.service
```

Ensure `gunicorn` and dependencies are installed in the virtualenv referenced by `ExecStart`.

