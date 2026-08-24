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
