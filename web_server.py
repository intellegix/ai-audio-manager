#!/usr/bin/env python3
"""Web API for AI Audio Manager - Access from phone on local network"""

from flask import Flask, jsonify, request, render_template_string
import subprocess
import re
import json
from pathlib import Path

app = Flask(__name__)

# Configuration
CONFIG_FILE = Path.home() / ".config" / "ai-audio-manager" / "config.json"

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

CONFIG = load_config()
INPUT_SOURCE = CONFIG.get("audio", {}).get("input_source", "alsa_input.pci-0000_00_0e.0.analog-stereo")
OUTPUT_SINK = CONFIG.get("audio", {}).get("output_sink", "bluez_output.00_1F_47_E6_52_0C.1")
PRESETS = CONFIG.get("presets", {
    "movie": {"input": 120, "output": 85, "latency": 30},
    "music": {"input": 100, "output": 80, "latency": 20},
    "voice": {"input": 140, "output": 70, "latency": 25},
    "night": {"input": 80, "output": 50, "latency": 30}
})

loopback_module_id = None

def run_pactl(args):
    try:
        result = subprocess.run(["pactl"] + args, capture_output=True, text=True, timeout=5)
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)

def get_volume(target, is_source=True):
    cmd = "get-source-volume" if is_source else "get-sink-volume"
    success, output = run_pactl([cmd, target])
    if success:
        match = re.search(r'(\d+)%', output)
        if match:
            return int(match.group(1))
    return 100 if is_source else 80

def set_volume(target, percent, is_source=True):
    cmd = "set-source-volume" if is_source else "set-sink-volume"
    success, _ = run_pactl([cmd, target, f"{percent}%"])
    return success

def detect_loopback():
    global loopback_module_id
    success, output = run_pactl(["list", "short", "modules"])
    if success:
        for line in output.split('\n'):
            if 'module-loopback' in line and INPUT_SOURCE in line:
                parts = line.split('\t')
                if parts:
                    loopback_module_id = int(parts[0])
                    return True
    return False

def enable_loopback(latency_ms=30):
    global loopback_module_id
    if loopback_module_id is not None:
        return True
    success, output = run_pactl([
        "load-module", "module-loopback",
        f"source={INPUT_SOURCE}", f"sink={OUTPUT_SINK}",
        f"latency_msec={latency_ms}",
        "source_dont_move=true", "sink_dont_move=true"
    ])
    if success and output:
        loopback_module_id = int(output)
        return True
    return False

def disable_loopback():
    global loopback_module_id
    if loopback_module_id is None:
        return True
    success, _ = run_pactl(["unload-module", str(loopback_module_id)])
    if success:
        loopback_module_id = None
    return success

detect_loopback()

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
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.getElementById('input-vol').value = data.input;
                document.getElementById('output-vol').value = data.output;
                document.getElementById('latency').value = data.latency;
                document.getElementById('input-val').textContent = data.input + '%';
                document.getElementById('output-val').textContent = data.output + '%';
                document.getElementById('latency-val').textContent = data.latency + 'ms';
                document.getElementById('loopback-toggle').classList.toggle('active', data.loopback);
                document.getElementById('status').textContent = data.loopback ? '● Audio routing active' : '○ Audio routing disabled';
                document.getElementById('status').classList.toggle('active', data.loopback);
            } catch(e) { document.getElementById('status').textContent = '⚠ Connection error'; }
        }
        function debounce(fn, delay) { clearTimeout(debounceTimer); debounceTimer = setTimeout(fn, delay); }
        document.getElementById('input-vol').addEventListener('input', function() {
            document.getElementById('input-val').textContent = this.value + '%';
            debounce(() => fetch('/api/input/' + this.value, {method: 'POST'}), 100);
        });
        document.getElementById('output-vol').addEventListener('input', function() {
            document.getElementById('output-val').textContent = this.value + '%';
            debounce(() => fetch('/api/output/' + this.value, {method: 'POST'}), 100);
        });
        document.getElementById('latency').addEventListener('input', function() {
            document.getElementById('latency-val').textContent = this.value + 'ms';
            debounce(() => fetch('/api/latency/' + this.value, {method: 'POST'}), 300);
        });
        async function toggleLoopback() {
            const toggle = document.getElementById('loopback-toggle');
            await fetch('/api/loopback/' + (toggle.classList.contains('active') ? 'off' : 'on'), {method: 'POST'});
            toggle.classList.toggle('active'); fetchStatus();
        }
        async function applyPreset(name) { await fetch('/api/preset/' + name, {method: 'POST'}); fetchStatus(); }
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

@app.route('/api/status')
def get_status():
    return jsonify({
        'input': get_volume(INPUT_SOURCE, True),
        'output': get_volume(OUTPUT_SINK, False),
        'latency': CONFIG.get("audio", {}).get("default_latency_ms", 30),
        'loopback': loopback_module_id is not None
    })

@app.route('/api/input/<int:volume>', methods=['POST'])
def set_input(volume):
    success = set_volume(INPUT_SOURCE, max(0, min(150, volume)), True)
    return jsonify({'success': success, 'value': volume})

@app.route('/api/output/<int:volume>', methods=['POST'])
def set_output(volume):
    success = set_volume(OUTPUT_SINK, max(0, min(100, volume)), False)
    return jsonify({'success': success, 'value': volume})

@app.route('/api/latency/<int:ms>', methods=['POST'])
def set_latency(ms):
    ms = max(10, min(100, ms))
    if loopback_module_id is not None:
        disable_loopback()
        enable_loopback(ms)
    return jsonify({'success': True, 'value': ms})

@app.route('/api/loopback/<state>', methods=['POST'])
def set_loopback(state):
    success = enable_loopback() if state == 'on' else disable_loopback()
    return jsonify({'success': success, 'active': loopback_module_id is not None})

@app.route('/api/preset/<name>', methods=['POST'])
def apply_preset(name):
    if name in PRESETS:
        preset = PRESETS[name]
        set_volume(INPUT_SOURCE, preset['input'], True)
        set_volume(OUTPUT_SINK, preset['output'], False)
        if loopback_module_id is not None:
            disable_loopback()
            enable_loopback(preset['latency'])
        return jsonify({'success': True, 'preset': name})
    return jsonify({'success': False}), 404

if __name__ == '__main__':
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except: local_ip = '127.0.0.1'
    finally: s.close()
    print(f"\n{'='*50}\n  AI Audio Manager - Web Control\n{'='*50}")
    print(f"\n  Open on your phone:\n  http://{local_ip}:5000\n\n{'='*50}\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
