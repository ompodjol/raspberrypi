from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from functools import wraps
from flask import Response
import json
import os
import threading
import time

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'sensors.json')
lock = threading.Lock()

app = Flask(__name__)
CORS(app)

# Simple basic-auth for admin endpoints (username/password in env for prototype)
ADMIN_USER = os.environ.get('RPM_ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('RPM_ADMIN_PASS', 'password')


def check_auth(user, pw):
    return user == ADMIN_USER and pw == ADMIN_PASS


def authenticate():
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login"'})


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
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


@app.route('/health')
def health():
    return 'ok'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
