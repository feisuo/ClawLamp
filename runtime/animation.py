import argparse
import os
import sys
import time
from typing import Any


# Allow running as a script from the runtime directory.
sys.path.append(os.path.dirname(os.path.dirname(__file__)))


def _import_animation_service():
    # Lazy import so this module can be imported without hardware deps installed.
    from lelamp.service.motors.animation_service import AnimationService  # type: ignore

    return AnimationService


def _import_rgb_service():
    from lelamp.service.rgb.rgb_service import RGBService  # type: ignore

    return RGBService


DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_LAMP_ID = "lelamp"
DEFAULT_FPS = 30
DEFAULT_DURATION = 3.0
DEFAULT_IDLE_RECORDING = "idle"
DEFAULT_WAIT_SECONDS = 2.0

# LED strip defaults (aligned with runtime/main.py)
DEFAULT_LED_COUNT = 64
DEFAULT_LED_PIN = 12
DEFAULT_LED_FREQ_HZ = 800000
DEFAULT_LED_DMA = 10
DEFAULT_LED_BRIGHTNESS = 255
DEFAULT_LED_INVERT = False
DEFAULT_LED_CHANNEL = 0

# Recording name -> solid RGB while the motion plays (and held after, same as motor pose).
RECORDING_RGB: dict[str, tuple[int, int, int]] = {
    "idle": (70, 70, 90),
    "curious": (0, 200, 255),
    "excited": (255, 90, 0),
    "happy_wiggle": (255, 200, 0),
    "headshake": (140, 0, 255),
    "nod": (0, 220, 120),
    "sad": (0, 60, 180),
    "scanning": (0, 255, 80),
    "shock": (255, 255, 255),
    "shy": (255, 140, 180),
    "wake_up": (255, 235, 200),
}
DEFAULT_RECORDING_RGB: tuple[int, int, int] = (255, 255, 255)

_rgb_service: Any = None
_rgb_started: bool = False


def _resolve_rgb_for_play(recording_name: str, payload: dict[str, Any]) -> tuple[int, int, int] | None:
    """Return (r,g,b) or None if LED should be skipped."""
    if payload.get("led") is False:
        return None
    raw = payload.get("rgb")
    if raw is not None:
        if isinstance(raw, (list, tuple)) and len(raw) == 3:
            try:
                r, g, b = (int(raw[0]), int(raw[1]), int(raw[2]))
            except (TypeError, ValueError):
                raise ValueError("payload.rgb must be three integers")
            if not all(0 <= v <= 255 for v in (r, g, b)):
                raise ValueError("payload.rgb values must be 0..255")
            return (r, g, b)
        raise ValueError("payload.rgb must be a list or tuple of 3 integers")
    return RECORDING_RGB.get(recording_name, DEFAULT_RECORDING_RGB)


def _apply_led_solid(color: tuple[int, int, int]) -> dict[str, Any]:
    """Best-effort solid color; never raises."""
    global _rgb_service, _rgb_started
    try:
        RGBService = _import_rgb_service()
        if _rgb_service is None:
            _rgb_service = RGBService(
                led_count=DEFAULT_LED_COUNT,
                led_pin=DEFAULT_LED_PIN,
                led_freq_hz=DEFAULT_LED_FREQ_HZ,
                led_dma=DEFAULT_LED_DMA,
                led_brightness=DEFAULT_LED_BRIGHTNESS,
                led_invert=DEFAULT_LED_INVERT,
                led_channel=DEFAULT_LED_CHANNEL,
            )
        if not _rgb_started:
            _rgb_service.start()
            _rgb_started = True
        _rgb_service.dispatch("solid", color)
        return {"led": True, "rgb": list(color)}
    except Exception as e:
        return {"led": False, "led_error": str(e)}


class MotorAnimation:
    """
    Thin wrapper around AnimationService using the dispatch("play", ...) interface.
    """

    def __init__(self) -> None:
        AnimationService = _import_animation_service()
        self._service: Any = AnimationService(
            port=DEFAULT_PORT,
            lamp_id=DEFAULT_LAMP_ID,
            fps=DEFAULT_FPS,
            duration=DEFAULT_DURATION,
            idle_recording=DEFAULT_IDLE_RECORDING,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._service.start()
        self._started = True

    def stop(self) -> None:
        self._service.stop(timeout=5.0)

    def get_available_recordings(self):
        return self._service.get_available_recordings()

    def play(self, recording_name: str) -> None:
        self._service.dispatch("play", recording_name)


# Strong reference: keep service running after call_motor returns so pose is maintained.
_motor_anim: MotorAnimation | None = None


def call_motor(payload: dict[str, Any]) -> dict[str, Any]:
    """
    External API: dict payload with `play`; optional LED control.

    - `play`: recording name (required).
    - `rgb`: optional [r, g, b] 0..255; overrides default color for this recording.
    - `led`: optional False to skip LED (motor only).

    Example: {"play": "wake_up"}
    Example: {"play": "sad", "rgb": [0, 0, 255]}
    """
    recording_name = payload.get("play")
    if not isinstance(recording_name, str) or not recording_name.strip():
        return {"ok": False, "error": "payload.play is required and must be a non-empty string"}

    recording_name = recording_name.strip()
    try:
        color = _resolve_rgb_for_play(recording_name, payload)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    global _motor_anim

    try:
        if _motor_anim is None:
            _motor_anim = MotorAnimation()
    except ModuleNotFoundError as e:
        return {"ok": False, "error": f"missing dependency: {e}"}

    anim = _motor_anim
    anim.start()
    # Light LED first so it matches the start of the motion.
    if color is not None:
        led_info = _apply_led_solid(color)
    else:
        led_info = {"led": False, "led_skipped": True}
    anim.play(recording_name)
    time.sleep(DEFAULT_WAIT_SECONDS)
    # Do not call anim.stop(): keep connection and last pose.
    return {"ok": True, "play": recording_name, **led_info}


def _parse_cli_rgb(value: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError('rgb must be "R,G,B"')
    try:
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as e:
        raise argparse.ArgumentTypeError("rgb components must be integers") from e
    if not all(0 <= v <= 255 for v in (r, g, b)):
        raise argparse.ArgumentTypeError("rgb must be in 0..255")
    return (r, g, b)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Play motor animation with default runtime parameters")
    parser.add_argument("--play", type=str, required=True, help="Recording name to play, e.g. wake_up")
    parser.add_argument(
        "--rgb",
        type=_parse_cli_rgb,
        default=None,
        help='Override LED color as R,G,B (default: color mapped to recording)',
    )
    parser.add_argument("--no-led", action="store_true", help="Motor only, do not drive LEDs")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"play": args.play}
    if args.no_led:
        payload["led"] = False
    if args.rgb is not None:
        payload["rgb"] = list(args.rgb)

    result = call_motor(payload)
    print(result)
    if not result.get("ok"):
        return 1
    # Process exit would drop the serial connection; block so pose stays held.
    print("Maintaining current pose. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nExiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
