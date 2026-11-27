"""Render our source SVG into a native macOS application icon."""

import subprocess
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def create(root):
    folder = root / "build/VideoBot.iconset"
    folder.mkdir(parents=True, exist_ok=True)
    renderer = QSvgRenderer(str(root / "videobot/assets/videobot.svg"))
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            size = base * scale
            image = QImage(size, size, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            image.save(str(folder / f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"))
    subprocess.run(["iconutil", "-c", "icns", str(folder), "-o", str(root / "build/VideoBot.icns")], check=True)
