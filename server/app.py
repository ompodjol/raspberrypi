from flask import Flask, jsonify, request, abort
from flask_cors import CORS
import json
import os
import threading
import time

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, 'sensors.json')
lock = threading.Lock()

app = Flask(__name__)
CORS(app)


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


@app.route('/health')
def health():
    return 'ok'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
