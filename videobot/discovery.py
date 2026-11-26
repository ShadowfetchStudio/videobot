"""Native extractor enumeration, followed by bounded same-origin browser discovery."""

import re
from urllib.parse import urljoin, urlsplit

import yt_dlp
from yt_dlp.extractor import gen_extractor_classes

from .downloader import common_options
from .models import Candidate, normalize_url
from .runtime import redact

MEDIA_EXTENSIONS = (
    ".mp4",
    ".webm",
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".m4v",
    ".ogv",
    ".3gp",
    ".wmv",
    ".mpeg",
    ".mpg",
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
)
MANIFEST_EXTENSIONS = (".m3u8", ".mpd")

# Raw string is essential: Python must not reinterpret JavaScript \b, \s or URL escapes.
SCAN = r"""() => {
 const absolute = value => { try { const u = new URL(value, document.baseURI); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; } };
 const media = new Set();
 const add = value => { if (value) { const u=absolute(value); if(u) media.add(u); } };
 for(const e of document.querySelectorAll('video[src],video source[src],audio[src],audio source[src]')) add(e.getAttribute('src'));
 for(const e of document.querySelectorAll('meta[property="og:video"],meta[property="og:video:url"],meta[property="og:video:secure_url"]')) add(e.content);
 for(const attr of ['data-video-url','data-video','data-mp4','data-stream','data-file','data-video-src','data-src'])
   for(const e of document.querySelectorAll(`[${attr}]`)) {
     const value=e.getAttribute(attr);
     if(attr !== 'data-src' || /\.(mp4|webm|m3u8|mpd)(?:[?#]|$)/i.test(value || '') || ['VIDEO','SOURCE'].includes(e.tagName)) add(value);
   }
 let walked=0;
 const visit = (value,depth=0) => {
   if(!value || typeof value !== 'object' || depth>15 || ++walked>5000) return;
   if([].concat(value['@type'] || []).some(t => /(?:^|\/)VideoObject$/.test(t))) { add(value.contentUrl); add(value.embedUrl); }
   for(const v of Object.values(value)) { if(Array.isArray(v)) v.forEach(x=>visit(x,depth+1)); else if(v && typeof v==='object') visit(v,depth+1); }
 };
 for(const e of document.querySelectorAll('script[type="application/ld+json"]')) { try { visit(JSON.parse(e.textContent)); } catch {} }
 for(const e of document.querySelectorAll('iframe[src]')) {
   try { const h=new URL(e.src).hostname; if(/(^|\.)(youtube\.com|youtube-nocookie\.com|youtu\.be|vimeo\.com|dailymotion\.com|twitch\.tv)$/.test(h)) add(e.src); } catch {}
 }
 const items=[]; let next=null;
 for(const a of document.querySelectorAll('a[href]')) {
   const raw=a.getAttribute('href') || ''; const href=absolute(raw);
   if(!href || raw.startsWith('#')) continue;
   if(/\.(mp4|webm|mkv|mov|avi|flv|m4v|ogv|3gp|wmv|mpeg|mpg|mp3|m4a|wav|m3u8|mpd)(?:[?#]|$)/i.test(href)) { add(href); continue; }
   const text=(a.textContent || '').trim();
   if(a.rel==='next' || /^(next|next page|more|load more)\s*[»›>]?$/i.test(text) || /^[»›>]$/.test(text) || /\bnext\b/i.test(a.className)) { next ||= href; continue; }
   if(new URL(href).origin !== location.origin || /\b(login|signin|signup|register|about|contact|privacy|terms|search|tag|category|author)\b/i.test(href)) continue;
   let score=0;
   if(a.querySelector('img,video')) score+=6;
   if(a.closest('[class*="card"],[class*="item"],[class*="grid"],[class*="video"],[class*="post"]')) score+=4;
   if(/\/(videos?|watch|view|post|item|media|clip|play|detail|reel|shorts?)\//i.test(href) || /[?&]v=/.test(href)) score+=4;
   if(score>=4) items.push({url:href,title:a.title || text || a.getAttribute('aria-label') || ''});
 }
 const rel=document.querySelector('link[rel="next"]'); if(rel) next=absolute(rel.href);
 return {media:[...media],items,next,title:document.title};
}"""


def is_native(url):
    return any(cls.IE_NAME != "generic" and cls.suitable(url) for cls in gen_extractor_classes())


def candidate_from_info(info, fallback):
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or fallback
    if not str(url).startswith(("http://", "https://")):
        if info.get("ie_key") == "Youtube":
            url = "https://www.youtube.com/watch?v=" + str(info.get("id", url))
        else:
            return None
    formats = [
        {
            "id": f.get("format_id"),
            "height": f.get("height"),
            "ext": f.get("ext"),
            "bytes": f.get("filesize") or f.get("filesize_approx"),
            "note": f.get("format_note"),
        }
        for f in info.get("formats", [])
    ]
    return Candidate(
        normalize_url(url),
        info.get("title") or "",
        info.get("extractor_key") or info.get("ie_key") or "",
        str(info.get("id") or ""),
        info.get("duration"),
        info.get("thumbnail") or "",
        info.get("uploader") or info.get("channel") or "",
        formats,
    )


class Discovery:
    def __init__(self, options, cancel, emit):
        self.options = options.validate()
        self.cancel = cancel
        self.emit = emit
        self.seen = set()
        self.items = []
        self.cookies = []

    def add(self, candidate):
        if not candidate:
            return
        candidate.url = normalize_url(candidate.url)
        if candidate.url not in self.seen and len(self.items) < self.options.max_items:
            self.seen.add(candidate.url)
            self.items.append(candidate)
            self.emit("candidate", candidate=candidate.to_dict())

    def inspect(self, urls):
        for raw in urls:
            self.cancel.check()
            url = normalize_url(raw)
            if len(self.items) >= self.options.max_items:
                self.emit("log", level="warning", message="Item budget reached; discovery is truncated.")
                break
            path = urlsplit(url).path.lower()
            if path.endswith(MEDIA_EXTENSIONS):
                self.add(Candidate(url, path.rsplit("/", 1)[-1], direct=True))
            elif is_native(url) or path.endswith(MANIFEST_EXTENSIONS):
                self._native(url)
            else:
                self._browser(url)
        if len(self.items) >= self.options.max_items:
            self.emit("log", level="warning", message="Item budget reached; inspect another batch to continue.")
        return self.items

    def _native(self, url):
        opts = common_options(self.options, self.emit, self.cancel)
        opts.update(
            {
                "extract_flat": "in_playlist",
                "lazy_playlist": True,
                "playlistend": self.options.max_items - len(self.items),
                "noplaylist": False,
                "skip_download": True,
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

            def collect(entry, depth=0):
                self.cancel.check()
                if not entry or depth > 8 or len(self.items) >= self.options.max_items:
                    return
                if entry.get("entries") is not None:
                    for sub in entry["entries"]:
                        collect(sub, depth + 1)
                        if len(self.items) >= self.options.max_items:
                            break
                else:
                    self.add(candidate_from_info(entry, url))

            collect(info)

    def _browser(self, url):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context()
                if self.options.cookie_file or self.options.cookie_browser:
                    from yt_dlp.cookies import load_cookies

                    jar = load_cookies(
                        self.options.cookie_file or None,
                        (self.options.cookie_browser,) if self.options.cookie_browser else None,
                        None,
                    )
                    cookies = []
                    for cookie in jar:
                        data = {
                            "name": cookie.name,
                            "value": cookie.value,
                            "domain": cookie.domain,
                            "path": cookie.path or "/",
                            "secure": cookie.secure,
                        }
                        if cookie.expires and cookie.expires > 0:
                            data["expires"] = cookie.expires
                        cookies.append(data)
                    ctx.add_cookies(cookies)
                page = ctx.new_page()
                page.set_default_timeout(3000)
                pending = [url]
                visited = set()
                pages = 0
                origin = urlsplit(url).netloc
                while pending and pages < self.options.max_pages and len(self.items) < self.options.max_items:
                    self.cancel.check()
                    current = normalize_url(pending.pop(0))
                    if current in visited:
                        continue
                    visited.add(current)
                    if is_native(current):
                        self._native(current)
                        continue
                    self.emit("log", message="Inspecting " + redact(current))
                    response = page.goto(current, wait_until="domcontentloaded", timeout=15000)
                    if response and response.status >= 400:
                        raise RuntimeError(f"Listing returned HTTP {response.status}")
                    if urlsplit(page.url).netloc != origin:
                        self.emit(
                            "log", level="warning", message="Skipped navigation redirect outside the collection domain."
                        )
                        continue
                    pages += 1
                    previous = None
                    stable = 0
                    # Bounded adaptive scroll; completion depends on stable discoveries, not a six-scroll assumption.
                    for _ in range(30):
                        self.cancel.check()
                        data = page.evaluate(SCAN)
                        fingerprint = (tuple(data["media"]), tuple(i["url"] for i in data["items"]))
                        stable = stable + 1 if fingerprint == previous else 0
                        previous = fingerprint
                        if stable >= 3:
                            break
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        self.cancel.wait(0.4)
                    else:
                        self.emit(
                            "log", level="warning", message="Scroll budget reached; this page may have more items."
                        )
                    button_rounds = 0
                    while True:
                        self.cancel.check()
                        data = page.evaluate(SCAN)
                        for src in data["media"]:
                            direct = urlsplit(src).path.lower().endswith(MEDIA_EXTENSIONS) and not is_native(src)
                            self.add(Candidate(src, data["title"], referer=current, direct=direct))
                        # If this is a detail page, avoid collecting its recommended-video cards.
                        if not data["media"]:
                            for item in data["items"]:
                                target = normalize_url(item["url"])
                                if target not in visited and target not in pending:
                                    pending.append(target)
                        next_url = data["next"]
                        if next_url and urlsplit(urljoin(current, next_url)).netloc == origin:
                            target = normalize_url(urljoin(current, next_url))
                            if target not in visited and target not in pending:
                                pending.append(target)
                        if next_url or len(self.items) >= self.options.max_items or pages >= self.options.max_pages:
                            break
                        button = page.get_by_role(
                            "button", name=re.compile(r"^(next(?: page)?|load more|more)\s*[›»>]?$", re.I)
                        ).first
                        if not button.count() or not button.is_visible() or not button.is_enabled():
                            break
                        before = (tuple(data["media"]), tuple(i["url"] for i in data["items"]))
                        button.click()
                        self.cancel.wait(0.7)
                        if urlsplit(page.url).netloc != origin:
                            self.emit(
                                "log",
                                level="warning",
                                message="Stopped a pagination redirect outside the collection domain.",
                            )
                            break
                        if normalize_url(page.url) != current:
                            target = normalize_url(page.url)
                            if target in visited:
                                break
                            visited.add(target)
                            current = target
                        updated = page.evaluate(SCAN)
                        after = (tuple(updated["media"]), tuple(i["url"] for i in updated["items"]))
                        if before == after:
                            self.emit(
                                "log", level="warning", message="Pagination button produced no new items; stopped."
                            )
                            break
                        pages += 1
                        button_rounds += 1
                    self.cookies = ctx.cookies()
                if pending or pages >= self.options.max_pages:
                    self.emit(
                        "log",
                        level="warning",
                        message="Page budget reached or items remain; discovery may be incomplete.",
                    )
            finally:
                browser.close()
