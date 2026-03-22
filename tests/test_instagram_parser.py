from app.services.instagram import extract_reel_urls


def test_extract_reel_urls_deduplicates_and_canonicalizes() -> None:
    html = '''
    <a href="/reel/ABC123/">x</a>
    <a href="https://www.instagram.com/reel/XYZ789/?utm_source=ig_web">y</a>
    <script>"https://www.instagram.com/reel/ABC123/"</script>
    '''

    urls = extract_reel_urls(html)
    assert urls == [
        'https://www.instagram.com/reel/ABC123/',
        'https://www.instagram.com/reel/XYZ789/',
    ]
