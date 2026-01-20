# OBS Remote Controller

Advanced OBS Smart Controller for remote control via input devices.

## Installation

Install with pipx:

```bash
pipx install /path/to/obs-remote
```

Or from a git repository:

```bash
pipx install git+https://github.com/yourusername/obs-remote.git
```

## Usage

```bash
obs-remote --code 28 --host localhost --port 4455 --password yourpassword
```

### Arguments

- `--code`: Input event code (required, e.g., 28 for Enter key)
- `--host`: OBS WebSocket host (default: localhost)
- `--port`: OBS WebSocket port (default: 4455)
- `--password`: OBS WebSocket password (default: empty)

## Features

- Short press: Toggle recording
- Long press (1s): Launch/close OBS application
- Automatic device detection and monitoring
- WebSocket reconnection handling
