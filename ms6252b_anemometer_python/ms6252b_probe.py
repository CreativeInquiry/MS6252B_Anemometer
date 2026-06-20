#!/usr/bin/env python3
"""Raw serial probe for the Mastech MS6252B / CP210x stream.

The Processing sketch is useful once the packet format is known. This script is
for finding that format: it prints raw hex, printable ASCII, and ASCII with the
high bit stripped, and can scan likely UART settings.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import select
import sys
import termios
import time
from typing import Iterable


BAUDS = {
    1200: termios.B1200,
    2400: termios.B2400,
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


def configure(fd: int, baud: int, mode: str) -> None:
    if baud not in BAUDS:
        raise SystemExit(f"unsupported baud {baud}")

    data_bits = int(mode[0])
    parity = mode[1].upper()
    stop_bits = int(mode[2])

    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[3] = 0
    attrs[4] = BAUDS[baud]
    attrs[5] = BAUDS[baud]

    cflag = attrs[2]
    cflag &= ~termios.CSIZE
    cflag &= ~termios.PARENB
    cflag &= ~termios.PARODD
    cflag &= ~termios.CSTOPB
    if hasattr(termios, "CRTSCTS"):
        cflag &= ~termios.CRTSCTS

    cflag |= termios.CLOCAL | termios.CREAD
    cflag |= termios.CS7 if data_bits == 7 else termios.CS8
    if parity in ("E", "O"):
        cflag |= termios.PARENB
    if parity == "O":
        cflag |= termios.PARODD
    if stop_bits == 2:
        cflag |= termios.CSTOPB

    attrs[2] = cflag
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)


def capture(port: str, baud: int, mode: str, seconds: float) -> bytes:
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure(fd, baud, mode)
        data = bytearray()
        end = time.time() + seconds
        while time.time() < end:
            readable, _, _ = select.select([fd], [], [], 0.2)
            if not readable:
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if chunk:
                data.extend(chunk)
        return bytes(data)
    finally:
        os.close(fd)


def printable(data: Iterable[int]) -> str:
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data)


def score_printable(data: bytes) -> float:
    if not data:
        return 0.0
    good = sum(1 for b in data if b in (9, 10, 13) or 32 <= b <= 126)
    return good / len(data)


def numeric_candidates(text: str) -> list[str]:
    candidates = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    return candidates[:12]


def decode_frame(frame: bytes) -> tuple[float, float, float] | None:
    if len(frame) != 13:
        return None
    signature = (
        frame[1:3] == b"\x01\x01"
        and frame[4:6] == b"\x00\x00"
        and frame[8:10] == b"\x01\x01"
        and frame[12] == 0x03
    )
    if not signature:
        return None

    humidity_pct = int.from_bytes(frame[2:4], byteorder="big", signed=False) / 10.0
    temperature_c = int.from_bytes(frame[6:8], byteorder="big", signed=True) / 10.0
    wind_mps = int.from_bytes(frame[10:12], byteorder="big", signed=False) / 100.0
    return humidity_pct, temperature_c, wind_mps


def decoded_frames(data: bytes) -> list[tuple[int, float, float, float]]:
    frames = []
    for offset in range(0, max(0, len(data) - 12)):
        decoded = decode_frame(data[offset : offset + 13])
        if decoded is None:
            continue
        humidity_pct, temperature_c, wind_mps = decoded
        frames.append((offset, humidity_pct, temperature_c, wind_mps))
    return frames


def dump(data: bytes, limit: int = 512) -> None:
    print(f"bytes: {len(data)}")
    for off in range(0, min(len(data), limit), 16):
        chunk = data[off : off + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = printable(chunk)
        strip = printable(b & 0x7F for b in chunk)
        print(f"{off:04X}  {hx:<47}  {asc:<16}  strip7:{strip}")

    counts = collections.Counter(data)
    print("freq:", " ".join(f"{b:02X}:{n}" for b, n in counts.most_common(24)))

    raw_text = printable(data)
    strip_text = printable(b & 0x7F for b in data)
    print("raw numeric candidates:", ", ".join(numeric_candidates(raw_text)) or "(none)")
    print("strip7 numeric candidates:", ", ".join(numeric_candidates(strip_text)) or "(none)")

    frames = decoded_frames(data)
    if frames:
        print("decoded frames:")
        for offset, humidity_pct, temperature_c, wind_mps in frames[:24]:
            print(
                f"  @{offset:04X}  RH={humidity_pct:5.1f}%  "
                f"T={temperature_c:4.1f} C  wind={wind_mps:4.2f} m/s"
            )
    else:
        print("decoded frames: (none)")


def scan(port: str, seconds: float) -> None:
    modes = ("8N1", "7E1", "7O1", "8E1", "8O1")
    bauds = (2400, 4800, 9600, 19200, 38400)
    for baud in bauds:
        for mode in modes:
            try:
                data = capture(port, baud, mode, seconds)
            except OSError as exc:
                print(f"{baud}-{mode}: open/read failed: {exc}")
                return
            raw_score = score_printable(data)
            strip_score = score_printable(bytes(b & 0x7F for b in data))
            sample = printable(data[:48])
            strip_sample = printable(b & 0x7F for b in data[:48])
            print(
                f"{baud}-{mode}: bytes={len(data):4d} "
                f"printable={raw_score:.2f} strip7={strip_score:.2f} "
                f"raw='{sample}' strip7='{strip_sample}'"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", default="/dev/cu.usbserial-0001")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--mode", default="8N1")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()

    if args.scan:
        scan(args.port, args.seconds)
    else:
        data = capture(args.port, args.baud, args.mode.upper(), args.seconds)
        print(f"port: {args.port}  setting: {args.baud}-{args.mode.upper()}")
        dump(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
