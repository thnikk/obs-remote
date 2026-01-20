#!/usr/bin/env python3
import argparse
import sys
import asyncio
import subprocess
import time
import os
import psutil
import evdev
import signal
from evdev import InputDevice, categorize, ecodes
from obswebsocket import obsws, requests

# --- Configuration & Constants ---
LONG_PRESS_THRESHOLD = 1.0  
RECONNECT_DELAY = 5         
OBS_EXEC = "obs"            

def get_args():
    parser = argparse.ArgumentParser(description="Advanced OBS Smart Controller")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--password", default="")
    parser.add_argument("--code", type=int, required=True, help="Input code (e.g. 28)")
    return parser.parse_args()

class OBSController:
    def __init__(self, args):
        self.args = args
        self.client = obsws(args.host, port=args.port, password=args.password)
        self.connected = False
        self.active_devices = {}
        self.long_press_active = False

    def is_obs_running(self):
        """Checks if the obs process exists."""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and 'obs' in proc.info['name'].lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def toggle_obs_app(self):
        """Launches or closes OBS using the method confirmed to work on your system."""
        if self.is_obs_running():
            print("Closing OBS gracefully via SIGINT...")
            # Using the exact command you verified manually
            subprocess.run(["pkill", "-SIGINT", "obs"])
        else:
            print("Launching OBS...")
            clean_env = os.environ.copy()
            clean_env.pop("PYTHONPATH", None)
            clean_env.pop("PYTHONHOME", None)
            
            try:
                subprocess.Popen(
                    [OBS_EXEC],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                    start_new_session=True
                )
            except FileNotFoundError:
                print(f"Error: Command '{OBS_EXEC}' not found.")

    async def connect_obs(self):
        """Maintains the background WebSocket connection."""
        while True:
            if not self.connected:
                try:
                    self.client.connect()
                    self.connected = True
                    print("Connected to OBS WebSocket.")
                except Exception:
                    pass
            await asyncio.sleep(RECONNECT_DELAY)

    async def _check_long_press(self, device_path, trigger_code):
        """Triggers at exactly the 1s mark if key is still held."""
        await asyncio.sleep(LONG_PRESS_THRESHOLD)
        try:
            dev = InputDevice(device_path)
            # Use active_keys() to verify the button is physically still down
            if trigger_code in dev.active_keys():
                print("Hold detected: Toggling OBS Application.")
                self.long_press_active = True
                self.toggle_obs_app()
        except Exception:
            pass

    async def handle_events(self, device, trigger_code):
        """Handles the logic for short vs long presses."""
        press_start_time = 0
        try:
            async for event in device.async_read_loop():
                if event.type == ecodes.EV_KEY and event.code == trigger_code:
                    if event.value == 1:  # Key Down
                        press_start_time = time.time()
                        self.long_press_active = False
                        asyncio.create_task(self._check_long_press(device.path, trigger_code))
                    elif event.value == 0:  # Key Up
                        if not self.long_press_active:
                            duration = time.time() - press_start_time
                            if duration < LONG_PRESS_THRESHOLD and self.connected:
                                print(f"[{device.name}] Toggle Recording.")
                                try:
                                    self.client.call(requests.ToggleRecord())
                                except Exception:
                                    self.connected = False
        except (OSError, PermissionError):
            pass
        finally:
            self.active_devices.pop(device.path, None)

    async def watch_devices(self):
        """Watches for newly plugged-in hardware."""
        while True:
            for path in evdev.list_devices():
                if path not in self.active_devices:
                    try:
                        dev = InputDevice(path)
                        caps = dev.capabilities()
                        if ecodes.EV_KEY in caps and self.args.code in caps[ecodes.EV_KEY]:
                            print(f"Monitoring: {dev.name}")
                            task = asyncio.create_task(self.handle_events(dev, self.args.code))
                            self.active_devices[path] = task
                        else:
                            dev.close()
                    except (OSError, PermissionError):
                        continue
            await asyncio.sleep(2)

async def main():
    args = get_args()
    ctrl = OBSController(args)
    await asyncio.gather(ctrl.connect_obs(), ctrl.watch_devices())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
