import time
import sys
import os
import argparse

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from service.rgb import RGBService
from service.base import Priority

def _parse_rgb(value: str):
    v = value.strip()
    if v.startswith("#"):
        hexv = v[1:]
        if len(hexv) != 6:
            raise argparse.ArgumentTypeError("hex color must be like #RRGGBB")
        try:
            return (int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16))
        except ValueError as e:
            raise argparse.ArgumentTypeError("invalid hex color") from e

    parts = [p.strip() for p in v.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("color must be 'R,G,B' or '#RRGGBB'")
    try:
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as e:
        raise argparse.ArgumentTypeError("R,G,B must be integers") from e
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        raise argparse.ArgumentTypeError("R,G,B must be in [0,255]")
    return (r, g, b)

def solid_color(color, duration: float = 0.0):

    rgb_service = RGBService()
    rgb_service.start()
    try:
        rgb_service.dispatch("solid", color)
        if duration and duration > 0:
            time.sleep(duration)
    finally:
        rgb_service.stop()

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Simple RGB LED color control")
    p.add_argument("--color", type=_parse_rgb, required=True, help="R,G,B or #RRGGBB (e.g. 255,0,0)")
    p.add_argument("--duration", type=float, default=0.0, help="seconds to hold the color")
    args = p.parse_args(argv)

    solid_color(
        args.color,
        duration=args.duration,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())