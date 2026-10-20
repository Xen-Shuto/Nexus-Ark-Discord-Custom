"""Shared generated-image naming, monthly directories and legacy lookup."""

import datetime
from pathlib import Path
import re
import time
import uuid


def monthly_image_directory(rooms_dir, room_name, subdir):
    path = Path(rooms_dir) / room_name / subdir / datetime.datetime.now().strftime("%Y-%m")
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def save_generated_png(image, save_dir, room_name, provider):
    def component(value):
        return re.sub(r"[^\w.-]", "_", str(value)).strip(".") or "image"

    directory = Path(save_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{component(provider)}_{component(room_name.lower())}_{int(time.time())}_{uuid.uuid4().hex}.png"
    # Exclusive creation prevents overwriting even if a caller supplies a
    # repeated identifier. Remove only this new file when encoding fails.
    with path.open("xb") as output:
        try:
            image.save(output, "PNG")
        except Exception:
            output.close()
            path.unlink()
            raise
    return path.as_posix()


def find_generated_image(directory, filename):
    root = Path(directory)
    direct = root / filename
    if direct.is_file():
        return str(direct)
    if root.is_dir():
        for month in sorted(root.iterdir(), reverse=True):
            if month.is_dir() and re.fullmatch(r"\d{4}-\d{2}", month.name):
                candidate = month / filename
                if candidate.is_file():
                    return str(candidate)
    return None
