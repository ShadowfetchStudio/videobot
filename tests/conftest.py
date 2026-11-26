import os
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def media_site(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required")
    web = tmp_path / "web"
    web.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(web / "tiny.mp4"),
        ],
        check=True,
    )
    (web / "single.html").write_text('<title>Small but valid</title><video src="/tiny.mp4"></video>')
    (web / "gallery.html").write_text('<div class="card"><a href="/single.html">A video</a></div>')

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(web)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", web
    server.shutdown()
    server.server_close()
    thread.join()
