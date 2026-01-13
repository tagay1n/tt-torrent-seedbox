from ttseed.ingest import _parse_sitemap


def test_parse_sitemap_index():
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        "<sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    urls, sitemaps = _parse_sitemap(xml.encode("utf-8"))
    assert urls == []
    assert sitemaps == ["https://example.com/sitemap1.xml"]


def test_parse_sitemap_urlset():
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        "<url><loc>https://example.com/viewtopic.php?t=1</loc><lastmod>2024-01-01</lastmod></url>"
        "</urlset>"
    )
    urls, sitemaps = _parse_sitemap(xml.encode("utf-8"))
    assert sitemaps == []
    assert urls[0][0] == "https://example.com/viewtopic.php?t=1"
    assert urls[0][1] is not None
