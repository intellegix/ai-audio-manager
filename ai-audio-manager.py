#!/usr/bin/env python3
"""AI-Powered Audio Management System for TV → Bluetooth Speaker Bridge"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango
import json
import subprocess
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any

# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "ai-audio-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"

class AudioController:
    """PulseAudio interface via pactl commands"""

    def __init__(self, config: Dict):
        self.input_source = config["audio"]["input_source"]
        self.output_sink = config["audio"]["output_sink"]
        self.loopback_module_id: Optional[int] = None
        self._detect_existing_loopback()

    def _run_pactl(self, args: list) -> tuple[bool, str]:
        """Run pactl command and return (success, output)"""
        try:
            result = subprocess.run(
                ["pactl"] + args,
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            return False, str(e)

    def _detect_existing_loopback(self):
        """Detect if a loopback module already exists for our source/sink"""
        success, output = self._run_pactl(["list", "short", "modules"])
        if success:
            for line in output.split('\n'):
                if 'module-loopback' in line and self.input_source in line:
                    parts = line.split('\t')
                    if parts:
                        self.loopback_module_id = int(parts[0])
                        return

    def set_source_volume(self, percent: int) -> bool:
        """Set input source volume (0-150%)"""
        success, _ = self._run_pactl(["set-source-volume", self.input_source, f"{percent}%"])
        return success

    def set_sink_volume(self, percent: int) -> bool:
        """Set output sink volume (0-100%)"""
        success, _ = self._run_pactl(["set-sink-volume", self.output_sink, f"{percent}%"])
        return success

    def get_source_volume(self) -> int:
        """Get current input volume percentage"""
        success, output = self._run_pactl(["get-source-volume", self.input_source])
        if success:
            match = re.search(r'(\d+)%', output)
            if match:
                return int(match.group(1))
        return 100

    def get_sink_volume(self) -> int:
        """Get current output volume percentage"""
        success, output = self._run_pactl(["get-sink-volume", self.output_sink])
        if success:
            match = re.search(r'(\d+)%', output)
            if match:
                return int(match.group(1))
        return 80

    def enable_loopback(self, latency_ms: int = 30) -> bool:
        """Enable audio routing from TV to speaker"""
        if self.loopback_module_id is not None:
            return True  # Already enabled

        success, output = self._run_pactl([
            "load-module", "module-loopback",
            f"source={self.input_source}",
            f"sink={self.output_sink}",
            f"latency_msec={latency_ms}",
            "source_dont_move=true",
            "sink_dont_move=true"
        ])
        if success and output:
            self.loopback_module_id = int(output)
            return True
        return False

    def disable_loopback(self) -> bool:
        """Disable audio routing"""
        if self.loopback_module_id is None:
            return True

        success, _ = self._run_pactl(["unload-module", str(self.loopback_module_id)])
        if success:
            self.loopback_module_id = None
        return success

    def is_loopback_active(self) -> bool:
        """Check if loopback is currently active"""
        return self.loopback_module_id is not None

    def update_latency(self, latency_ms: int) -> bool:
        """Update latency by recreating loopback"""
        if self.loopback_module_id is not None:
            self.disable_loopback()
            return self.enable_loopback(latency_ms)
        return True


class ClaudeClient:
    """Claude API communication"""

    SYSTEM_PROMPT = """You are an audio management assistant. Parse user commands and return JSON actions.

Available actions:
- set_input_volume: 0-150 (TV input level)
- set_output_volume: 0-100 (speaker output level)
- set_latency: 10-100 (milliseconds)
- toggle_loopback: true/false
- apply_preset: movie/music/voice/night
- get_status: returns current settings
- auto_tune: analyze and suggest optimal settings

Current state: {current_state}

Respond ONLY with JSON: {{"action": "...", "value": ..., "explanation": "..."}}
For auto_tune, return: {{"action": "auto_tune", "value": {{"input": X, "output": Y, "latency": Z}}, "explanation": "..."}}
For general questions, return: {{"action": "info", "value": null, "explanation": "your helpful response"}}"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._httpx = None

    def _get_httpx(self):
        """Lazy load httpx to save memory"""
        if self._httpx is None:
            import httpx
            self._httpx = httpx
        return self._httpx

    def send_message(self, user_message: str, current_state: Dict) -> Dict:
        """Send message to Claude and get parsed response"""
        if not self.api_key:
            return {
                "action": "error",
                "value": None,
                "explanation": "API key not configured. Please add your Claude API key to ~/.config/ai-audio-manager/config.json"
            }

        httpx = self._get_httpx()

        system_prompt = self.SYSTEM_PROMPT.format(
            current_state=json.dumps(current_state)
        )

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 256,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_message}]
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["content"][0]["text"]
                    # Extract JSON from response
                    try:
                        # Handle potential markdown code blocks
                        if "```" in content:
                            match = re.search(r'```(?:json)?\s*(.*?)```', content, re.DOTALL)
                            if match:
                                content = match.group(1)
                        return json.loads(content.strip())
                    except json.JSONDecodeError:
                        return {
                            "action": "info",
                            "value": None,
                            "explanation": content
                        }
                else:
                    return {
                        "action": "error",
                        "value": None,
                        "explanation": f"API error: {response.status_code}"
                    }
        except Exception as e:
            return {
                "action": "error",
                "value": None,
                "explanation": f"Connection error: {str(e)}"
            }


class MainWindow(Gtk.Window):
    """Main GTK3 application window"""

    def __init__(self, config: Dict):
        super().__init__(title="AI Audio Manager")
        self.config = config
        self.audio = AudioController(config)
        self.claude = ClaudeClient(config.get("claude_api_key", ""))

        # Current settings
        self.input_volume = self.audio.get_source_volume()
        self.output_volume = self.audio.get_sink_volume()
        self.latency = config["audio"]["default_latency_ms"]

        self.set_default_size(500, 450)
        self.set_border_width(10)

        self._build_ui()
        self._update_status()

    def _build_ui(self):
        """Build the user interface"""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_box)

        # === Audio Control Panel ===
        audio_frame = Gtk.Frame(label=" Audio Controls ")
        audio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        audio_box.set_margin_start(10)
        audio_box.set_margin_end(10)
        audio_box.set_margin_top(5)
        audio_box.set_margin_bottom(10)
        audio_frame.add(audio_box)
        main_box.pack_start(audio_frame, False, False, 0)

        # Input Volume
        input_box = Gtk.Box(spacing=10)
        input_label = Gtk.Label(label="TV Input Volume")
        input_label.set_width_chars(16)
        input_label.set_xalign(0)
        input_box.pack_start(input_label, False, False, 0)

        self.input_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 5)
        self.input_scale.set_value(self.input_volume)
        self.input_scale.set_hexpand(True)
        self.input_scale.connect("value-changed", self._on_input_changed)
        input_box.pack_start(self.input_scale, True, True, 0)

        self.input_value = Gtk.Label(label=f"{self.input_volume}%")
        self.input_value.set_width_chars(5)
        input_box.pack_start(self.input_value, False, False, 0)
        audio_box.pack_start(input_box, False, False, 0)

        # Output Volume
        output_box = Gtk.Box(spacing=10)
        output_label = Gtk.Label(label="Speaker Output")
        output_label.set_width_chars(16)
        output_label.set_xalign(0)
        output_box.pack_start(output_label, False, False, 0)

        self.output_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.output_scale.set_value(self.output_volume)
        self.output_scale.set_hexpand(True)
        self.output_scale.connect("value-changed", self._on_output_changed)
        output_box.pack_start(self.output_scale, True, True, 0)

        self.output_value = Gtk.Label(label=f"{self.output_volume}%")
        self.output_value.set_width_chars(5)
        output_box.pack_start(self.output_value, False, False, 0)
        audio_box.pack_start(output_box, False, False, 0)

        # Latency
        latency_box = Gtk.Box(spacing=10)
        latency_label = Gtk.Label(label="Latency (ms)")
        latency_label.set_width_chars(16)
        latency_label.set_xalign(0)
        latency_box.pack_start(latency_label, False, False, 0)

        self.latency_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        self.latency_scale.set_value(self.latency)
        self.latency_scale.set_hexpand(True)
        self.latency_scale.connect("value-changed", self._on_latency_changed)
        latency_box.pack_start(self.latency_scale, True, True, 0)

        self.latency_value = Gtk.Label(label=f"{self.latency}")
        self.latency_value.set_width_chars(5)
        latency_box.pack_start(self.latency_value, False, False, 0)
        audio_box.pack_start(latency_box, False, False, 0)

        # Loopback toggle
        self.loopback_check = Gtk.CheckButton(label="Enable TV → Speaker Routing")
        self.loopback_check.set_active(self.audio.is_loopback_active())
        self.loopback_check.connect("toggled", self._on_loopback_toggled)
        audio_box.pack_start(self.loopback_check, False, False, 5)

        # Presets
        preset_box = Gtk.Box(spacing=10)
        preset_label = Gtk.Label(label="Presets:")
        preset_box.pack_start(preset_label, False, False, 0)

        for preset_name in ["Movie", "Music", "Voice", "Night"]:
            btn = Gtk.Button(label=preset_name)
            btn.connect("clicked", self._on_preset_clicked, preset_name.lower())
            preset_box.pack_start(btn, False, False, 0)

        audio_box.pack_start(preset_box, False, False, 5)

        # === AI Chat Panel ===
        ai_frame = Gtk.Frame(label=" AI Assistant ")
        ai_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        ai_box.set_margin_start(10)
        ai_box.set_margin_end(10)
        ai_box.set_margin_top(5)
        ai_box.set_margin_bottom(10)
        ai_frame.add(ai_box)
        main_box.pack_start(ai_frame, True, True, 0)

        # Chat display
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(120)

        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.chat_view.set_left_margin(5)
        self.chat_view.set_right_margin(5)
        self.chat_buffer = self.chat_view.get_buffer()

        # Create tags for styling
        self.chat_buffer.create_tag("ai", foreground="#2E7D32", weight=Pango.Weight.BOLD)
        self.chat_buffer.create_tag("user", foreground="#1565C0", weight=Pango.Weight.BOLD)
        self.chat_buffer.create_tag("error", foreground="#C62828")

        scroll.add(self.chat_view)
        ai_box.pack_start(scroll, True, True, 0)

        # Add welcome message
        self._append_chat("AI", "Ready to help with audio settings. Try 'make it louder' or 'movie mode'.")

        # Input area
        input_row = Gtk.Box(spacing=5)
        self.chat_entry = Gtk.Entry()
        self.chat_entry.set_placeholder_text("Type a command...")
        self.chat_entry.connect("activate", self._on_send_clicked)
        input_row.pack_start(self.chat_entry, True, True, 0)

        send_btn = Gtk.Button(label="Send")
        send_btn.connect("clicked", self._on_send_clicked)
        input_row.pack_start(send_btn, False, False, 0)

        ai_box.pack_start(input_row, False, False, 0)

        # === Status Bar ===
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0)
        main_box.pack_start(self.status_label, False, False, 0)

    def _update_status(self):
        """Update status bar"""
        if self.audio.is_loopback_active():
            self.status_label.set_markup("● <span foreground='#2E7D32'>Audio routing active</span>")
        else:
            self.status_label.set_markup("○ <span foreground='#757575'>Audio routing disabled</span>")

    def _append_chat(self, sender: str, message: str, is_error: bool = False):
        """Add message to chat display"""
        end_iter = self.chat_buffer.get_end_iter()

        if self.chat_buffer.get_char_count() > 0:
            self.chat_buffer.insert(end_iter, "\n")
            end_iter = self.chat_buffer.get_end_iter()

        tag = "error" if is_error else ("ai" if sender == "AI" else "user")
        self.chat_buffer.insert_with_tags_by_name(end_iter, f"{sender}: ", tag)
        end_iter = self.chat_buffer.get_end_iter()
        self.chat_buffer.insert(end_iter, message)

        # Scroll to bottom
        GLib.idle_add(self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self):
        adj = self.chat_view.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _get_current_state(self) -> Dict:
        """Get current audio state for AI context"""
        return {
            "input": int(self.input_scale.get_value()),
            "output": int(self.output_scale.get_value()),
            "latency": int(self.latency_scale.get_value()),
            "loopback": self.audio.is_loopback_active()
        }

    def _apply_ai_action(self, response: Dict):
        """Apply action from AI response"""
        action = response.get("action")
        value = response.get("value")
        explanation = response.get("explanation", "Done.")

        if action == "set_input_volume" and value is not None:
            self.input_scale.set_value(int(value))
        elif action == "set_output_volume" and value is not None:
            self.output_scale.set_value(int(value))
        elif action == "set_latency" and value is not None:
            self.latency_scale.set_value(int(value))
        elif action == "toggle_loopback" and value is not None:
            self.loopback_check.set_active(bool(value))
        elif action == "apply_preset" and value in self.config["presets"]:
            self._apply_preset(value)
        elif action == "auto_tune" and isinstance(value, dict):
            if "input" in value:
                self.input_scale.set_value(int(value["input"]))
            if "output" in value:
                self.output_scale.set_value(int(value["output"]))
            if "latency" in value:
                self.latency_scale.set_value(int(value["latency"]))
        elif action == "error":
            self._append_chat("AI", explanation, is_error=True)
            return

        self._append_chat("AI", explanation)

    def _apply_preset(self, preset_name: str):
        """Apply a preset configuration"""
        if preset_name in self.config["presets"]:
            preset = self.config["presets"][preset_name]
            self.input_scale.set_value(preset["input"])
            self.output_scale.set_value(preset["output"])
            self.latency_scale.set_value(preset["latency"])

    # Event handlers
    def _on_input_changed(self, scale):
        value = int(scale.get_value())
        self.input_value.set_text(f"{value}%")
        self.audio.set_source_volume(value)

    def _on_output_changed(self, scale):
        value = int(scale.get_value())
        self.output_value.set_text(f"{value}%")
        self.audio.set_sink_volume(value)

    def _on_latency_changed(self, scale):
        value = int(scale.get_value())
        self.latency_value.set_text(f"{value}")
        if self.audio.is_loopback_active():
            self.audio.update_latency(value)

    def _on_loopback_toggled(self, button):
        if button.get_active():
            latency = int(self.latency_scale.get_value())
            self.audio.enable_loopback(latency)
        else:
            self.audio.disable_loopback()
        self._update_status()

    def _on_preset_clicked(self, button, preset_name):
        self._apply_preset(preset_name)
        self._append_chat("AI", f"Applied {preset_name.title()} preset.")

    def _on_send_clicked(self, widget):
        text = self.chat_entry.get_text().strip()
        if not text:
            return

        self.chat_entry.set_text("")
        self._append_chat("You", text)

        # Process in background to keep UI responsive
        GLib.idle_add(self._process_ai_request, text)

    def _process_ai_request(self, text: str):
        """Process AI request (called from idle)"""
        state = self._get_current_state()
        response = self.claude.send_message(text, state)
        self._apply_ai_action(response)
        return False


def load_config() -> Dict:
    """Load configuration from file"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def main():
    config = load_config()
    if not config:
        print(f"Error: Configuration not found at {CONFIG_FILE}")
        print("Please create the config file with your Claude API key.")
        return 1

    win = MainWindow(config)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    exit(main())
