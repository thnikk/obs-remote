#!/usr/bin/env python3 -u
import argparse
import sys
import asyncio
import subprocess
import time
import os
import psutil
import evdev
from evdev import InputDevice, categorize, ecodes
from obswebsocket import obsws, requests


LONG_PRESS_THRESHOLD = 1.0
RECONNECT_DELAY = 2
OBS_EXEC = "obs"
TOGGLE_COOLDOWN = 2.0


def get_args():
    parser = argparse.ArgumentParser(
        description="Advanced OBS Smart Controller"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--code",
        type=int,
        required=True,
        help="Input code (e.g. 28)"
    )
    return parser.parse_args()


class OBSController:
    def __init__(self, args):
        self.args = args
        self.client = obsws(
            args.host,
            port=args.port,
            password=args.password
        )
        self.connected = False
        self.active_devices = {}
        self.long_press_active = False
        self.last_toggle_time = 0

    def is_obs_running(self):
        """Check if the obs process exists and is not zombie."""
        for proc in psutil.process_iter(['name', 'status', 'pid', 'exe']):
            try:
                proc_name = proc.info['name']
                if not proc_name:
                    continue

                proc_name_lower = proc_name.lower()

                # Skip this script's process
                if proc.info['pid'] == os.getpid():
                    continue

                # Skip Python processes
                if 'python' in proc_name_lower:
                    continue

                # Skip our own binary (obs-remote)
                if 'obs-remote' in proc_name_lower:
                    continue

                # Look for actual OBS process
                if 'obs' in proc_name_lower:
                    if proc.info['status'] in [
                        psutil.STATUS_ZOMBIE,
                        psutil.STATUS_DEAD
                    ]:
                        continue
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def is_recording(self):
        """Check if OBS is currently recording."""
        if not self.connected:
            return False
        try:
            response = self.client.call(requests.GetRecordStatus())
            return response.datain.get('outputActive', False)
        except Exception:
            self.connected = False
            return False

    def toggle_obs_app(self):
        """Launch or close OBS with cooldown."""
        current_time = time.time()
        if current_time - self.last_toggle_time < TOGGLE_COOLDOWN:
            return

        self.last_toggle_time = current_time

        obs_pid = self.is_obs_running()
        if obs_pid:
            if self.is_recording():
                print("Cannot close OBS: Recording is active.")
                return
            print(f"Closing OBS (PID {obs_pid}) gracefully...")
            try:
                os.kill(obs_pid, 2)
            except ProcessLookupError:
                pass
            self.connected = False
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
                self.connected = False
            except FileNotFoundError:
                print(f"Error: Command '{OBS_EXEC}' not found.")

    async def connect_obs(self):
        """Maintain the background WebSocket connection."""
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
        """Trigger at exactly the 1s mark if key is still held."""
        await asyncio.sleep(LONG_PRESS_THRESHOLD)
        try:
            dev = InputDevice(device_path)
            if trigger_code in dev.active_keys():
                print("Hold detected: Toggling OBS Application.")
                self.long_press_active = True
                self.toggle_obs_app()
        except Exception:
            pass

    async def handle_events(self, device, trigger_code):
        """Handle the logic for short vs long presses."""
        press_start_time = 0
        try:
            async for event in device.async_read_loop():
                if (event.type == ecodes.EV_KEY and
                        event.code == trigger_code):
                    if event.value == 1:
                        press_start_time = time.time()
                        self.long_press_active = False
                        asyncio.create_task(
                            self._check_long_press(
                                device.path,
                                trigger_code
                            )
                        )
                    elif event.value == 0:
                        if not self.long_press_active:
                            duration = time.time() - press_start_time
                            if (duration < LONG_PRESS_THRESHOLD and
                                    self.connected):
                                print(
                                    f"[{device.name}] Toggle Recording."
                                )
                                try:
                                    self.client.call(
                                        requests.ToggleRecord()
                                    )
                                except Exception:
                                    self.connected = False
        except (OSError, PermissionError):
            pass
        finally:
            self.active_devices.pop(device.path, None)

    async def watch_devices(self):
        """Watch for newly plugged-in hardware."""
        while True:
            for path in evdev.list_devices():
                if path not in self.active_devices:
                    try:
                        dev = InputDevice(path)
                        caps = dev.capabilities()
                        if (ecodes.EV_KEY in caps and
                                self.args.code in caps[ecodes.EV_KEY]):
                            print(f"Monitoring: {dev.name}")
                            task = asyncio.create_task(
                                self.handle_events(dev, self.args.code)
                            )
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


def main_cli():
    """Entry point for pipx installation."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main_cli()
