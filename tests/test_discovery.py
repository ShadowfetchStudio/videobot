from videobot.discovery import SCAN, Discovery
from videobot.models import Options
from videobot.runtime import Cancellation


def page_for(browser, html):
    page = browser.new_page()
    page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html))
    page.goto("https://example.com/start")
    return page


def test_relative_nested_sources_and_no_thumbnail_substring_veto(browser):
    page = page_for(
        browser,
        '<meta property="og:video" content="/lexicon.mp4"><script type="application/ld+json">{"@graph":[{"@type":["VideoObject"],"contentUrl":"/nested.mp4"}]}</script>',
    )
    data = page.evaluate(SCAN)
    assert set(data["media"]) == {"https://example.com/lexicon.mp4", "https://example.com/nested.mp4"}
    page.close()


def test_scope_fragments_login_and_large_listing(browser):
    html = '<a href="https://ads.invalid"><img></a><a href="/login"><img></a><a href="#top"><img></a>'
    html += "".join(f'<div class="card"><a href="/watch/{i}">Item{i}</a></div>' for i in range(205))
    page = page_for(browser, html)
    data = page.evaluate(SCAN)
    assert len(data["items"]) == 205
    assert all("/watch/" in item["url"] for item in data["items"])
    page.close()


def test_single_and_gallery_discover_same_media(media_site, tmp_path):
    origin, _ = media_site
    for endpoint in ("single.html", "gallery.html"):
        events = []
        d = Discovery(
            Options(destination=str(tmp_path), max_pages=5), Cancellation(), lambda k, **v: events.append((k, v))
        )
        items = d.inspect([origin + "/" + endpoint])
        assert len(items) == 1 and items[0].url == origin + "/tiny.mp4"
        assert items[0].direct


def test_cycle_finishes(media_site, tmp_path):
    origin, web = media_site
    (web / "a.html").write_text('<a rel="next" href="/b.html">Next</a>')
    (web / "b.html").write_text('<a rel="next" href="/a.html">Next</a>')
    events = []
    d = Discovery(
        Options(destination=str(tmp_path), max_pages=10), Cancellation(), lambda k, **v: events.append((k, v))
    )
    assert d.inspect([origin + "/a.html"]) == []
    assert len([e for e in events if e[0] == "log" and e[1]["message"].startswith("Inspecting")]) == 2


def test_button_pagination(media_site, tmp_path):
    origin, web = media_site
    (web / "buttons.html").write_text(
        """<div id="items"></div><button onclick="document.querySelector('#items').innerHTML='<video src=/tiny.mp4></video>';this.remove()">Load more</button>"""
    )
    items = Discovery(Options(destination=str(tmp_path)), Cancellation(), lambda *a, **k: None).inspect(
        [origin + "/buttons.html"]
    )
    assert len(items) == 1 and items[0].url == origin + "/tiny.mp4"
