#!/usr/bin/env python3
"""
Render Relay Server - Accepts mobile requests and forwards to local machine via WebSocket
Deploy this to Render as a web service
"""

from flask import Flask, request, jsonify, render_template_string
from flask_sock import Sock
import json
import time
import threading
import uuid

app = Flask(__name__)
sock = Sock(app)

# Store for connected local clients and pending requests
local_clients = {}  # ws_id -> websocket
pending_requests = {}  # request_id -> {event, response}
client_lock = threading.Lock()

MOBILE_UI = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Audio Control</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff; min-height: 100vh; padding: 20px;
        }
        .container { max-width: 400px; margin: 0 auto; }
        h1 { text-align: center; font-size: 1.5rem; margin-bottom: 20px; color: #00d4ff; }
        .card {
            background: rgba(255,255,255,0.1); border-radius: 16px;
            padding: 20px; margin-bottom: 16px; backdrop-filter: blur(10px);
        }
        .slider-group { margin-bottom: 20px; }
        .slider-label { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 0.9rem; color: #aaa; }
        .slider-value { color: #00d4ff; font-weight: bold; }
        input[type="range"] {
            width: 100%; height: 8px; border-radius: 4px;
            background: #333; outline: none; -webkit-appearance: none;
        }
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none; width: 28px; height: 28px; border-radius: 50%;
            background: #00d4ff; cursor: pointer; box-shadow: 0 2px 10px rgba(0,212,255,0.5);
        }
        .toggle-container { display: flex; align-items: center; justify-content: space-between; padding: 12px 0; }
        .toggle {
            width: 60px; height: 32px; background: #333; border-radius: 16px;
            position: relative; cursor: pointer; transition: background 0.3s;
        }
        .toggle.active { background: #00d4ff; }
        .toggle::after {
            content: ''; position: absolute; width: 26px; height: 26px;
            background: #fff; border-radius: 50%; top: 3px; left: 3px; transition: transform 0.3s;
        }
        .toggle.active::after { transform: translateX(28px); }
        .presets { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .preset-btn {
            padding: 16px; border: none; border-radius: 12px; font-size: 1rem;
            font-weight: 600; cursor: pointer; transition: transform 0.1s;
        }
        .preset-btn:active { transform: scale(0.95); }
        .preset-movie { background: linear-gradient(135deg, #e74c3c, #c0392b); color: #fff; }
        .preset-music { background: linear-gradient(135deg, #9b59b6, #8e44ad); color: #fff; }
        .preset-voice { background: linear-gradient(135deg, #3498db, #2980b9); color: #fff; }
        .preset-night { background: linear-gradient(135deg, #2c3e50, #1a252f); color: #fff; }
        .status { text-align: center; padding: 12px; font-size: 0.85rem; color: #888; }
        .status.active { color: #00d4ff; }
        .status.error { color: #e74c3c; }
        .quick-btns { display: flex; gap: 10px; margin-top: 10px; }
        .quick-btn {
            flex: 1; padding: 12px; border: 2px solid #00d4ff; background: transparent;
            color: #00d4ff; border-radius: 8px; font-size: 1.2rem; cursor: pointer;
        }
        .quick-btn:active { background: rgba(0,212,255,0.2); }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔊 Audio Control</h1>
        <div class="card">
            <div class="slider-group">
                <div class="slider-label"><span>TV Input</span><span class="slider-value" id="input-val">100%</span></div>
                <input type="range" id="input-vol" min="0" max="150" value="100">
                <div class="quick-btns">
                    <button class="quick-btn" onclick="adjustVolume('input', -10)">−</button>
                    <button class="quick-btn" onclick="adjustVolume('input', 10)">+</button>
                </div>
            </div>
            <div class="slider-group">
                <div class="slider-label"><span>Speaker Output</span><span class="slider-value" id="output-val">80%</span></div>
                <input type="range" id="output-vol" min="0" max="100" value="80">
                <div class="quick-btns">
                    <button class="quick-btn" onclick="adjustVolume('output', -10)">−</button>
                    <button class="quick-btn" onclick="adjustVolume('output', 10)">+</button>
                </div>
            </div>
            <div class="slider-group">
                <div class="slider-label"><span>Latency</span><span class="slider-value" id="latency-val">30ms</span></div>
                <input type="range" id="latency" min="10" max="100" value="30">
            </div>
            <div class="toggle-container">
                <span>TV → Speaker Routing</span>
                <div class="toggle" id="loopback-toggle" onclick="toggleLoopback()"></div>
            </div>
        </div>
        <div class="card">
            <div class="presets">
                <button class="preset-btn preset-movie" onclick="applyPreset('movie')">🎬 Movie</button>
                <button class="preset-btn preset-music" onclick="applyPreset('music')">🎵 Music</button>
                <button class="preset-btn preset-voice" onclick="applyPreset('voice')">🎙 Voice</button>
                <button class="preset-btn preset-night" onclick="applyPreset('night')">🌙 Night</button>
            </div>
        </div>
        <div class="status" id="status">Connecting...</div>
    </div>
    <script>
        let debounceTimer;
        async function apiCall(endpoint, method='GET') {
            try {
                const res = await fetch('/api' + endpoint, {method, timeout: 10000});
                if (!res.ok) throw new Error('Not connected');
                return await res.json();
            } catch(e) {
                document.getElementById('status').textContent = '⚠ Home server offline';
                document.getElementById('status').className = 'status error';
                throw e;
            }
        }
        async function fetchStatus() {
            try {
                const data = await apiCall('/status');
                document.getElementById('input-vol').value = data.input;
                document.getElementById('output-vol').value = data.output;
                document.getElementById('latency').value = data.latency;
                document.getElementById('input-val').textContent = data.input + '%';
                document.getElementById('output-val').textContent = data.output + '%';
                document.getElementById('latency-val').textContent = data.latency + 'ms';
                document.getElementById('loopback-toggle').classList.toggle('active', data.loopback);
                document.getElementById('status').textContent = data.loopback ? '● Audio routing active' : '○ Audio routing disabled';
                document.getElementById('status').className = 'status' + (data.loopback ? ' active' : '');
            } catch(e) {}
        }
        function debounce(fn, delay) { clearTimeout(debounceTimer); debounceTimer = setTimeout(fn, delay); }
        document.getElementById('input-vol').addEventListener('input', function() {
            document.getElementById('input-val').textContent = this.value + '%';
            debounce(() => apiCall('/input/' + this.value, 'POST'), 150);
        });
        document.getElementById('output-vol').addEventListener('input', function() {
            document.getElementById('output-val').textContent = this.value + '%';
            debounce(() => apiCall('/output/' + this.value, 'POST'), 150);
        });
        document.getElementById('latency').addEventListener('input', function() {
            document.getElementById('latency-val').textContent = this.value + 'ms';
            debounce(() => apiCall('/latency/' + this.value, 'POST'), 300);
        });
        async function toggleLoopback() {
            const toggle = document.getElementById('loopback-toggle');
            try {
                await apiCall('/loopback/' + (toggle.classList.contains('active') ? 'off' : 'on'), 'POST');
                toggle.classList.toggle('active'); fetchStatus();
            } catch(e) {}
        }
        async function applyPreset(name) { try { await apiCall('/preset/' + name, 'POST'); fetchStatus(); } catch(e) {} }
        function adjustVolume(type, delta) {
            const slider = document.getElementById(type + '-vol');
            slider.value = Math.max(0, Math.min(type === 'input' ? 150 : 100, parseInt(slider.value) + delta));
            slider.dispatchEvent(new Event('input'));
        }
        fetchStatus(); setInterval(fetchStatus, 5000);
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(MOBILE_UI)

@app.route('/health')
def health():
    with client_lock:
        connected = len(local_clients) > 0
    return jsonify({'status': 'ok', 'local_connected': connected})

def forward_to_local(path, method='GET'):
    """Forward request to local machine via WebSocket"""
    with client_lock:
        if not local_clients:
            return jsonify({'error': 'Local server not connected'}), 503
        # Get first available client
        ws_id, ws = next(iter(local_clients.items()))

    request_id = str(uuid.uuid4())
    event = threading.Event()
    pending_requests[request_id] = {'event': event, 'response': None}

    try:
        # Send request to local machine
        ws.send(json.dumps({
            'id': request_id,
            'path': path,
            'method': method
        }))

        # Wait for response (timeout 10s)
        if event.wait(timeout=10):
            response = pending_requests[request_id]['response']
            del pending_requests[request_id]
            if response:
                return jsonify(response)
            return jsonify({'error': 'Empty response'}), 500
        else:
            del pending_requests[request_id]
            return jsonify({'error': 'Timeout'}), 504
    except Exception as e:
        if request_id in pending_requests:
            del pending_requests[request_id]
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    return forward_to_local('/api/status', 'GET')

@app.route('/api/input/<int:volume>', methods=['POST'])
def api_input(volume):
    return forward_to_local(f'/api/input/{volume}', 'POST')

@app.route('/api/output/<int:volume>', methods=['POST'])
def api_output(volume):
    return forward_to_local(f'/api/output/{volume}', 'POST')

@app.route('/api/latency/<int:ms>', methods=['POST'])
def api_latency(ms):
    return forward_to_local(f'/api/latency/{ms}', 'POST')

@app.route('/api/loopback/<state>', methods=['POST'])
def api_loopback(state):
    return forward_to_local(f'/api/loopback/{state}', 'POST')

@app.route('/api/preset/<name>', methods=['POST'])
def api_preset(name):
    return forward_to_local(f'/api/preset/{name}', 'POST')

@sock.route('/tunnel')
def tunnel(ws):
    """WebSocket endpoint for local machine to connect"""
    ws_id = str(uuid.uuid4())
    print(f"Local client connected: {ws_id}")

    with client_lock:
        local_clients[ws_id] = ws

    try:
        while True:
            message = ws.receive()
            if message is None:
                break

            data = json.loads(message)
            request_id = data.get('id')

            if request_id and request_id in pending_requests:
                pending_requests[request_id]['response'] = data.get('response')
                pending_requests[request_id]['event'].set()
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        with client_lock:
            if ws_id in local_clients:
                del local_clients[ws_id]
        print(f"Local client disconnected: {ws_id}")

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
