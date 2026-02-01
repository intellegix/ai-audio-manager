#!/usr/bin/env python3
"""
Tunnel Client - Long-polling based relay to Render
Run this on the local machine alongside web_server.py
"""

import requests
import time
import threading
import os
import sys

# Configuration
RENDER_URL = os.environ.get('RENDER_URL', 'https://ai-audio-manager.onrender.com')
LOCAL_API = 'http://127.0.0.1:5000'
POLL_TIMEOUT = 30
RETRY_DELAY = 5

session = requests.Session()

def handle_request(req):
    """Forward request to local API and return response"""
    try:
        path = req['path']
        method = req['method']
        request_id = req['id']

        url = LOCAL_API + path
        if method == 'POST':
            resp = session.post(url, timeout=5)
        else:
            resp = session.get(url, timeout=5)

        # Send response back to Render
        session.post(
            f"{RENDER_URL}/tunnel/respond",
            json={'id': request_id, 'response': resp.json()},
            timeout=5
        )
        print(f"  Handled: {method} {path}")
    except Exception as e:
        print(f"  Error handling request: {e}")
        try:
            session.post(
                f"{RENDER_URL}/tunnel/respond",
                json={'id': req.get('id'), 'response': {'error': str(e)}},
                timeout=5
            )
        except:
            pass

def poll_loop():
    """Main polling loop"""
    consecutive_errors = 0

    while True:
        try:
            # Long-poll for requests
            resp = session.get(
                f"{RENDER_URL}/tunnel/poll",
                timeout=POLL_TIMEOUT
            )

            if resp.status_code == 200:
                data = resp.json()
                req = data.get('request')
                if req:
                    handle_request(req)
                consecutive_errors = 0
            else:
                print(f"Poll error: {resp.status_code}")
                consecutive_errors += 1

        except requests.exceptions.Timeout:
            # Normal timeout, just continue polling
            consecutive_errors = 0
            continue

        except Exception as e:
            print(f"Connection error: {e}")
            consecutive_errors += 1

        if consecutive_errors > 3:
            print(f"Multiple errors, waiting {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
            consecutive_errors = 0

def keep_alive():
    """Ping Render periodically to prevent spin-down"""
    while True:
        time.sleep(300)  # Every 5 minutes
        try:
            resp = session.get(f"{RENDER_URL}/health", timeout=10)
            if resp.status_code == 200:
                print("Keep-alive ping OK")
        except Exception as e:
            print(f"Keep-alive failed: {e}")

def main():
    print("=" * 50)
    print("  AI Audio Manager - Tunnel Client")
    print("=" * 50)
    print(f"  Relay: {RENDER_URL}")
    print(f"  Local: {LOCAL_API}")
    print("=" * 50)
    print()

    # Verify local server is running
    try:
        resp = session.get(f"{LOCAL_API}/api/status", timeout=3)
        if resp.status_code == 200:
            print("✓ Local server connected")
        else:
            print("✗ Local server returned error")
    except:
        print("✗ Local server not running!")
        print("  Start it with: systemctl --user start ai-audio-manager")
        return

    # Verify Render is reachable
    try:
        resp = session.get(f"{RENDER_URL}/health", timeout=10)
        print(f"✓ Render server reachable")
    except Exception as e:
        print(f"✗ Cannot reach Render: {e}")
        print("  Will retry...")

    print()
    print("Listening for requests...")
    print()

    # Start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()

    # Start polling
    poll_loop()

if __name__ == '__main__':
    main()
