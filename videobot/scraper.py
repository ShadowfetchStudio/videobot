"""Compatibility adapter for the original SmartVideoScraper interface.

New integrations should use videobot.engine and the durable queue directly.
"""

from .discovery import Discovery
from .engine import run_queue
from .models import Options
from .runtime import Cancelled, Cancellation
from .storage import Store


class SmartVideoScraper:
    def __init__(self, url, save_dir, quality="best", fmt="mp4", max_pages=50, callbacks=None):
        self.url = url
        self.options = Options(
            destination=save_dir,
            quality=quality.removesuffix("p"),
            container="native" if fmt == "any" else fmt,
            max_pages=max_pages or 10000,
        )
        self.callbacks = callbacks or {}
        self.cancel = Cancellation()

    def stop(self):
        self.cancel.event.set()

    def run(self):
        def emit(kind, **data):
            if kind == "log" and "log" in self.callbacks:
                self.callbacks["log"](data["message"])
            elif kind == "progress" and data.get("percent") is not None and "progress" in self.callbacks:
                self.callbacks["progress"](int(data["percent"]))

        store = Store()
        try:
            items = Discovery(self.options, self.cancel, emit).inspect([self.url])
            ids = [store.add(item, self.options)[0] for item in items]
            status = run_queue(store.path, self.cancel, emit, ids=ids)
            result = {
                "status": status,
                "items": len(items),
                "videos": sum(j["status"] == "completed" for j in store.rows() if j["id"] in ids),
            }
            if "done" in self.callbacks:
                self.callbacks["done"](result)
        except Cancelled:
            if "done" in self.callbacks:
                self.callbacks["done"]({"status": "cancelled", "videos": 0})
        except Exception as exc:
            if "error" in self.callbacks:
                self.callbacks["error"](str(exc))
        finally:
            store.close()
