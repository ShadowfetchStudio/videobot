"""Serializable boundaries shared by the desktop app, CLI and worker process."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalize_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter an HTTP(S) URL without embedded credentials.")
    # Keep queries intact: signed links and playlist identities depend on them.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


@dataclass
class Options:
    destination: str = str(Path.home() / "Downloads" / "VideoBot")
    quality: str = "best"
    container: str = "native"
    audio_only: bool = False
    subtitles: str = ""
    automatic_subtitles: bool = False
    thumbnail: bool = False
    embed_metadata: bool = True
    editing_compatible: bool = False
    segment_start: float | None = None
    segment_end: float | None = None
    max_pages: int = 50
    max_items: int = 2000
    max_bytes: int = 10 * 1024**3
    min_free_bytes: int = 512 * 1024**2
    retries: int = 3
    cooldown: float = 5.0
    cookie_file: str = ""
    cookie_browser: str = ""
    rights_notes: str = "Unknown — verify rights before reuse."

    def validate(self):
        self.destination = str(Path(self.destination).expanduser().resolve())
        if self.quality not in ("best", "worst", "2160", "1080", "720", "480", "360"):
            raise ValueError("Unsupported quality setting.")
        if self.container not in ("native", "mp4", "webm"):
            raise ValueError("Unsupported container.")
        if not 1 <= self.max_pages <= 10000 or not 1 <= self.max_items <= 100000:
            raise ValueError("Choose a positive bounded page/item budget.")
        if self.max_bytes < 1 or self.min_free_bytes < 0 or not 0 <= self.retries <= 10:
            raise ValueError("Invalid disk budget or retry count.")
        if self.cooldown < 5:
            raise ValueError("The post-download cooldown must be at least five seconds.")
        if self.cookie_file and self.cookie_browser:
            raise ValueError("Choose either a cookie file or a browser, not both.")
        if self.cookie_browser not in ("", "chrome", "chromium", "firefox", "edge", "brave", "safari"):
            raise ValueError("Unsupported cookie browser.")
        if self.cookie_file and not Path(self.cookie_file).expanduser().is_file():
            raise ValueError("The selected cookie file does not exist.")
        if self.segment_start is not None or self.segment_end is not None:
            if self.segment_start is None or self.segment_end is None or not 0 <= self.segment_start < self.segment_end:
                raise ValueError("Segment start/end must satisfy 0 <= start < end.")
        if self.editing_compatible and (self.audio_only or self.container == "webm"):
            raise ValueError("Editing-compatible output requires video and MP4/native container.")
        return self

    def public_dict(self):
        data = asdict(self)
        # Authentication selections are runtime-only, never queue/settings/manifest data.
        data.pop("cookie_file")
        data.pop("cookie_browser")
        return data


@dataclass
class Candidate:
    url: str
    title: str = ""
    extractor: str = ""
    media_id: str = ""
    duration: float | None = None
    thumbnail: str = ""
    creator: str = ""
    formats: list[dict] = field(default_factory=list)
    referer: str = ""
    direct: bool = False

    def to_dict(self):
        return asdict(self)
