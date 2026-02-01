#!/usr/bin/env python3
"""
Tunnel Client - Connects to Render relay and forwards requests to local web server
Run this on the local machine alongside web_server.py
"""

import json
import time
import threading
import websocket
import requests
import os
import sys

# Configuration
RENDER_URL = os.environ.get('RENDER_URL', '')  # e.g., wss://ai-audio-manager.onrender.com/tunnel
LOCAL_API = 'http://127.0.0.1:5000'
RECONNECT_DELAY = 5

def on_message(ws, message):
    """Handle incoming request from relay server"""
    try:
        data = json.loads(message)
        request_id = data.get('id')
        path = data.get('path', '/')
        method = data.get('method', 'GET')

        # Forward to local API
        url = LOCAL_API + path
        if method == 'POST':
            response = requests.post(url, timeout=5)
        else:
            response = requests.get(url, timeout=5)

        # Send response back
        ws.send(json.dumps({
            'id': request_id,
            'response': response.json()
        }))
    except Exception as e:
        print(f"Error handling request: {e}")
        if request_id:
            ws.send(json.dumps({
                'id': request_id,
                'response': {'error': str(e)}
            }))

def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"Connection closed. Reconnecting in {RECONNECT_DELAY}s...")

def on_open(ws):
    print("Connected to relay server!")

def connect_loop():
    """Maintain persistent connection to relay server"""
    if not RENDER_URL:
        print("Error: RENDER_URL environment variable not set")
        print("Usage: RENDER_URL=wss://your-app.onrender.com/tunnel python3 tunnel_client.py")
        sys.exit(1)

    while True:
        try:
            print(f"Connecting to {RENDER_URL}...")
            ws = websocket.WebSocketApp(
                RENDER_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"Connection failed: {e}")

        time.sleep(RECONNECT_DELAY)

if __name__ == '__main__':
    print("AI Audio Manager - Tunnel Client")
    print("=" * 40)
    connect_loop()
