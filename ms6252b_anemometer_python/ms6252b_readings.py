#!/usr/bin/env python3
"""Print live MS6252B readings from the USB serial stream."""

from __future__ import annotations

import argparse
import os
import select
import sys
import time

from ms6252b_probe import configure, decode_frame


def frame_hex(frame: bytes) -> str:
    return " ".join(f"{b:02X}" for b in frame)


def read_frames(port: str, baud: int, mode: str, show_raw: bool, once: bool) -> None:
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure(fd, baud, mode)
        tail = bytearray()

        print(f"reading {port} at {baud}-{mode}; press Ctrl-C to stop", flush=True)
        while True:
            readable, _, _ = select.select([fd], [], [], 0.5)
            if not readable:
                continue

            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue

            for b in chunk:
                tail.append(b)
                if len(tail) > 13:
                    del tail[0 : len(tail) - 13]

                if b != 0x03 or len(tail) < 13:
                    continue

                frame = bytes(tail)
                decoded = decode_frame(frame)
                if decoded is None:
                    continue

                humidity_pct, temperature_c, wind_mps = decoded
                stamp = time.strftime("%H:%M:%S")
                line = (
                    f"{stamp}  wind={wind_mps:5.2f} m/s  "
                    f"temp={temperature_c:5.1f} C  RH={humidity_pct:5.1f}%"
                )
                if show_raw:
                    line += f"  frame={frame_hex(frame)}"
                print(line, flush=True)

                if once:
                    return
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print live wind, temperature, and RH readings from an MS6252B."
    )
    parser.add_argument("port", nargs="?", default="/dev/cu.usbserial-0001")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--mode", default="8N1")
    parser.add_argument("--raw", action="store_true", help="also print each packet in hex")
    parser.add_argument("--once", action="store_true", help="print one valid reading and exit")
    args = parser.parse_args()

    try:
        read_frames(args.port, args.baud, args.mode.upper(), args.raw, args.once)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
