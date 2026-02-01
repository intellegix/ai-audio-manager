# AI Audio Manager

AI-powered GTK3 desktop application for intelligent audio control of TV → Bluetooth speaker bridge.

## Features

- **Natural Language Chat** - Type commands like "make it louder" or "optimize for dialogue"
- **Smart Auto-Tuning** - AI analyzes settings and suggests optimal configurations
- **Full Audio Control** - Input/output volumes, loopback, latency adjustment
- **Presets** - Movie, Music, Voice, and Night modes

## Requirements

- Python 3.10+
- GTK3 (`python3-gi`)
- PulseAudio/PipeWire with `pactl`
- Claude API key

## Installation

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt install python3-gi

# Install Python dependencies
pip install -r requirements.txt

# Copy and configure
cp config.example.json ~/.config/ai-audio-manager/config.json
# Edit config.json and add your Claude API key

# Install to local bin
cp ai-audio-manager.py ~/.local/bin/
chmod +x ~/.local/bin/ai-audio-manager.py
```

## Configuration

Edit `~/.config/ai-audio-manager/config.json`:

```json
{
  "claude_api_key": "sk-ant-api03-...",
  "audio": {
    "input_source": "your_input_source",
    "output_sink": "your_output_sink",
    "default_latency_ms": 30
  }
}
```

Find your audio devices with:
```bash
pactl list short sources  # Input sources
pactl list short sinks    # Output sinks
```

## Usage

```bash
~/.local/bin/ai-audio-manager.py
```

Or search "AI Audio Manager" in your application menu.

### AI Commands

- "make it louder" / "quieter"
- "movie mode" / "music mode" / "night mode"
- "auto tune" - AI suggests optimal settings
- "what's the current status?"

## License

MIT
# Auto-deploy trigger
