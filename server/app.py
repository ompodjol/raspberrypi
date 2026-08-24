from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from functools import wraps
from flask import Response
import json
import os
import threading
import time
import jwt
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'sensors.json')
lock = threading.Lock()

app = Flask(__name__)
CORS(app)

# Simple auth configuration (env override for prototype)
ADMIN_USER = os.environ.get('RPM_ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('RPM_ADMIN_PASS', 'password')
JWT_SECRET = os.environ.get('RPM_SECRET', 'dev-secret')
JWT_EXP_SECONDS = int(os.environ.get('RPM_TOKEN_EXP', '3600'))


def check_auth(user, pw):
    return user == ADMIN_USER and pw == ADMIN_PASS


def authenticate():
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login"'})


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # First try bearer token
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
    return jsonify({'token': token})


@app.route('/health')
def health():
    return 'ok'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
