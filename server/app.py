from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from functools import wraps
from flask import Response
import json
import os
import platform
import subprocess
import threading
import time
import jwt
from urllib.parse import urlencode
from urllib.request import urlopen
from collections import deque
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DATA_FILE = os.path.join(BASE_DIR, 'sensors.json')
lock = threading.Lock()

app = Flask(__name__, static_folder=ROOT_DIR, static_url_path='')
CORS(app, supports_credentials=True)


@app.route('/')
def index():
    return app.send_static_file('index.html')


# Simple auth configuration (env override for prototype)
ADMIN_USER = os.environ.get('RPM_ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('RPM_ADMIN_PASS', 'password')
JWT_SECRET = os.environ.get('RPM_SECRET', 'dev-secret')
JWT_EXP_SECONDS = int(os.environ.get('RPM_TOKEN_EXP', '3600'))
TEMP_WARNING_C = float(os.environ.get('RPM_TEMP_WARNING_C', '70'))
TEMP_CRITICAL_C = float(os.environ.get('RPM_TEMP_CRITICAL_C', '80'))
CPU_WARNING_PERCENT = float(os.environ.get('RPM_CPU_WARNING_PERCENT', '80'))
CPU_CRITICAL_PERCENT = float(os.environ.get('RPM_CPU_CRITICAL_PERCENT', '95'))
thresholds = {
    'temperature_warning_c': TEMP_WARNING_C,
    'temperature_critical_c': TEMP_CRITICAL_C,
    'cpu_warning_percent': CPU_WARNING_PERCENT,
    'cpu_critical_percent': CPU_CRITICAL_PERCENT,
}
previous_cpu_stats = {}
cpu_history = deque(maxlen=60480)
process_history = deque(maxlen=60480)
history_lock = threading.Lock()
public_weather_cache = {}
public_weather_lock = threading.Lock()


def check_auth(user, pw):
    return user == ADMIN_USER and pw == ADMIN_PASS


def authenticate():
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login"'})


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Try cookie first (same-origin)
        token = request.cookies.get('rpm_token')
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
                request.user = payload.get('sub')
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return Response('Token expired', 401)
            except Exception:
                return Response('Invalid token', 401)

        # Try Authorization: Bearer header
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(None, 1)[1]
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
                request.user = payload.get('sub')
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return Response('Token expired', 401)
            except Exception:
                return Response('Invalid token', 401)

        # fallback to basic auth for convenience
        auth = request.authorization
        if auth and check_auth(auth.username, auth.password):
            request.user = auth.username
            return f(*args, **kwargs)

        return authenticate()

    return decorated


def load_sensors():
    if not os.path.exists(DATA_FILE):
        return []
    with lock:
        with open(DATA_FILE, 'r') as f:
            try:
                return json.load(f)
            except Exception:
                return []


def save_sensors(sensors):
    with lock:
        with open(DATA_FILE, 'w') as f:
            json.dump(sensors, f, indent=2)


def read_cpu_temperature():
    temperature_file = '/sys/class/thermal/thermal_zone0/temp'
    try:
        with open(temperature_file, 'r') as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def get_alarm_status(value, warning, critical):
    if value is None:
        return 'unavailable'
    if value >= critical:
        return 'critical'
    if value >= warning:
        return 'warning'
    return 'normal'


def read_processes(limit=24):
    try:
        result = subprocess.run(
            ['ps', '-eo', 'pid=,psr=,comm=,%cpu=,%mem=', '--sort=-%cpu'],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    processes = []
    for line in result.stdout.splitlines()[:limit]:
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            processes.append({
                'pid': int(parts[0]),
                'cpu_core': int(parts[1]) + 1,
                'name': parts[2],
                'cpu_percent': float(parts[3]),
                'memory_percent': float(parts[4]),
            })
        except ValueError:
            continue
    return processes[:limit]


def read_cpu_usage_by_core():
    current_stats = {}
    try:
        with open('/proc/stat', 'r') as f:
            for line in f:
                parts = line.split()
                if not parts or not parts[0].startswith('cpu') or not parts[0][3:].isdigit():
                    continue
                values = [int(value) for value in parts[1:]]
                current_stats[parts[0]] = (sum(values), values[3] + values[4])
    except (OSError, ValueError):
        return []

    usage = []
    for index, name in enumerate(sorted(current_stats, key=lambda value: int(value[3:]))):
        previous = previous_cpu_stats.get(name)
        total, idle = current_stats[name]
        if previous:
            total_delta = total - previous[0]
            idle_delta = idle - previous[1]
            busy_percent = round((1 - idle_delta / total_delta) * 100, 1) if total_delta else 0
        else:
            busy_percent = None
        usage.append({'name': f'CPU {index + 1}', 'usage_percent': busy_percent})
    previous_cpu_stats.clear()
    previous_cpu_stats.update(current_stats)
    return usage


def read_memory_info():
    values = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                name, value, _ = line.split()
                values[name.rstrip(':')] = int(value)
    except (OSError, ValueError):
        return None

    total = values.get('MemTotal')
    available = values.get('MemAvailable')
    if total is None or available is None:
        return None
    used = total - available
    return {
        'total_mb': round(total / 1024, 1),
        'used_mb': round(used / 1024, 1),
        'used_percent': round(used / total * 100, 1),
    }


def read_process_details(pid):
    process_dir = f'/proc/{pid}'
    if not os.path.isdir(process_dir):
        return None
    details = {'pid': pid}
    try:
        with open(os.path.join(process_dir, 'cmdline'), 'rb') as f:
            details['command'] = f.read().replace(b'\0', b' ').decode(errors='replace').strip()
    except (OSError, UnicodeError):
        details['command'] = None
    for key, filename in (('executable', 'exe'), ('working_directory', 'cwd')):
        try:
            details[key] = os.readlink(os.path.join(process_dir, filename))
        except OSError:
            details[key] = None
    try:
        with open(os.path.join(process_dir, 'status'), 'r') as f:
            for line in f:
                if line.startswith(('Name:', 'State:', 'Threads:', 'VmRSS:')):
                    key, value = line.split(':', 1)
                    details[key.lower()] = value.strip()
    except OSError:
        if not any(key in details for key in ('name', 'state', 'threads', 'vmrss')):
            return None
    return details


def get_public_weather(latitude, longitude):
    cache_key = (round(latitude, 4), round(longitude, 4))
    now = time.time()
    with public_weather_lock:
        cached = public_weather_cache.get(cache_key)
        if cached and now - cached['fetched_at'] < 300:
            return cached['data']

    query = urlencode({
        'latitude': latitude,
        'longitude': longitude,
        'current': 'temperature_2m,relative_humidity_2m',
        'hourly': 'temperature_2m,relative_humidity_2m',
        'past_days': 1,
        'forecast_days': 1,
        'timezone': 'auto',
    })
    try:
        with urlopen(f'https://api.open-meteo.com/v1/forecast?{query}', timeout=8) as response:
            payload = json.load(response)
        hourly = payload.get('hourly', {})
        data = {
            'source': 'Open-Meteo public weather reference',
            'latitude': latitude,
            'longitude': longitude,
            'current': payload.get('current', {}),
            'current_units': payload.get('current_units', {}),
            'hourly': {
                'time': hourly.get('time', []),
                'temperature_2m': hourly.get('temperature_2m', []),
                'relative_humidity_2m': hourly.get('relative_humidity_2m', []),
            },
        }
    except (OSError, ValueError, KeyError):
        return None
    with public_weather_lock:
        public_weather_cache[cache_key] = {'fetched_at': now, 'data': data}
    return data


@app.route('/api/public/weather')
def public_weather():
    try:
        latitude = float(request.args.get('latitude', os.environ.get('RPM_PUBLIC_LAT', '59.3293')))
        longitude = float(request.args.get('longitude', os.environ.get('RPM_PUBLIC_LNG', '18.0686')))
    except ValueError:
        abort(400, 'latitude and longitude must be numeric')
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        abort(400, 'latitude or longitude out of range')
    data = get_public_weather(latitude, longitude)
    if data is None:
        return jsonify({'error': 'public weather source unavailable'}), 502
    return jsonify(data)


@app.route('/api/process/<int:pid>')
def get_process_details(pid):
    details = read_process_details(pid)
    if details is None:
        return jsonify({'error': 'process not found or inaccessible'}), 404
    return jsonify(details)


@app.route('/api/system')
def get_system_info():
    load_average = os.getloadavg()[0]
    cpu_count = os.cpu_count() or 1
    temperature_c = read_cpu_temperature()
    cpu_load_percent = round(min(load_average / cpu_count * 100, 100), 1)
    cpu_usage_by_core = read_cpu_usage_by_core()
    processes = read_processes()
    if cpu_usage_by_core and all(core['usage_percent'] is not None for core in cpu_usage_by_core):
        with history_lock:
            cpu_history.append({
                'timestamp': int(time.time()),
                'cores': cpu_usage_by_core,
                'temperature_c': temperature_c,
            })
            process_history.append({
                'timestamp': int(time.time()),
                'processes': processes,
            })
    temperature_status = get_alarm_status(temperature_c, thresholds['temperature_warning_c'], thresholds['temperature_critical_c'])
    cpu_status = get_alarm_status(cpu_load_percent, thresholds['cpu_warning_percent'], thresholds['cpu_critical_percent'])
    alarms = []
    if temperature_status in ('warning', 'critical'):
        alarms.append(f'CPU temperature {temperature_c:.1f}°C ({temperature_status})')
    if cpu_status in ('warning', 'critical'):
        alarms.append(f'CPU load {cpu_load_percent:.1f}% ({cpu_status})')
    return jsonify({
        'temperature_c': temperature_c,
        'cpu_load_percent': cpu_load_percent,
        'cpu_cores': cpu_count,
        'cpu_usage_by_core': cpu_usage_by_core,
        'hostname': platform.node(),
        'platform': platform.platform(),
        'memory': read_memory_info(),
        'temperature_status': temperature_status,
        'cpu_status': cpu_status,
        'processes': processes,
        'alarms': alarms,
        'thresholds': thresholds,
    })


@app.route('/api/system/history')
def get_system_history():
    try:
        minutes = max(1, min(int(request.args.get('minutes', '60')), 10080))
    except ValueError:
        abort(400, 'minutes must be an integer')
    cutoff = int(time.time()) - minutes * 60
    with history_lock:
        samples = [sample for sample in cpu_history if sample['timestamp'] >= cutoff]
    return jsonify(samples)


@app.route('/api/system/process-history')
def get_process_history():
    try:
        minutes = max(1, min(int(request.args.get('minutes', '60')), 10080))
    except ValueError:
        abort(400, 'minutes must be an integer')
    cutoff = int(time.time()) - minutes * 60
    with history_lock:
        samples = [sample for sample in process_history if sample['timestamp'] >= cutoff]
    return jsonify(samples)


@app.route('/api/system/thresholds', methods=['POST'])
def update_thresholds():
    data = request.get_json() or {}
    try:
        updated = {key: float(data[key]) for key in thresholds}
    except (KeyError, TypeError, ValueError):
        abort(400, 'all threshold values must be numeric')

    if not (0 <= updated['temperature_warning_c'] < updated['temperature_critical_c']):
        abort(400, 'temperature warning must be below critical')
    if not (0 <= updated['cpu_warning_percent'] < updated['cpu_critical_percent'] <= 100):
        abort(400, 'CPU warning must be below critical and at most 100')

    thresholds.update(updated)
    return jsonify(thresholds)


@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    return jsonify(load_sensors())


@app.route('/api/sensors', methods=['POST'])
def add_sensor():
    data = request.get_json()
    if not data or 'name' not in data or 'lat' not in data or 'lng' not in data:
        abort(400, 'invalid payload')

    try:
        lat = float(data['lat'])
        lng = float(data['lng'])
    except Exception:
        abort(400, 'lat/lng must be numeric')

    sensors = load_sensors()
    new = {
        'id': int(time.time() * 1000),
        'name': data.get('name'),
        'lat': lat,
        'lng': lng,
        'info': data.get('info', '')
    }
    sensors.append(new)
    save_sensors(sensors)
    return jsonify(new), 201


@app.route('/api/sensors/<int:sensor_id>', methods=['DELETE'])
@requires_auth
def delete_sensor(sensor_id):
    sensors = load_sensors()
    new_list = [s for s in sensors if int(s.get('id')) != int(sensor_id)]
    if len(new_list) == len(sensors):
        return jsonify({'error': 'not found'}), 404
    save_sensors(new_list)
    return jsonify({'status': 'deleted'})


@app.route('/api/auth', methods=['POST'])
def auth_token():
    data = request.get_json() or {}
    user = data.get('username')
    pw = data.get('password')
    if not user or not pw:
        abort(400, 'username/password required')

    if not check_auth(user, pw):
        return Response('Unauthorized', 401)

    now = int(time.time())
    payload = {
        'sub': user,
        'iat': now,
        'exp': now + JWT_EXP_SECONDS
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    # return token and set HttpOnly session cookie (same-origin)
    resp = jsonify({'token': token})
    resp.set_cookie('rpm_token', token, httponly=True, samesite='Lax', max_age=JWT_EXP_SECONDS)
    return resp


@app.route('/api/login', methods=['POST'])
def login_cookie():
    # same as /api/auth but sets cookie only
    data = request.get_json() or {}
    user = data.get('username')
    pw = data.get('password')
    if not user or not pw:
        abort(400, 'username/password required')
    if not check_auth(user, pw):
        return Response('Unauthorized', 401)
    now = int(time.time())
    payload = {'sub': user, 'iat': now, 'exp': now + JWT_EXP_SECONDS}
    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    resp = jsonify({'status': 'ok'})
    resp.set_cookie('rpm_token', token, httponly=True, samesite='Lax', max_age=JWT_EXP_SECONDS)
    return resp


@app.route('/api/logout', methods=['POST'])
def logout():
    resp = jsonify({'status': 'logged out'})
    resp.set_cookie('rpm_token', '', expires=0)
    return resp


@app.route('/health')
def health():
    return 'ok'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
