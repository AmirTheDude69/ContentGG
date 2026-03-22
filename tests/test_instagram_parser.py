from app.services.instagram import extract_collection_id, extract_reel_urls, _extract_reels_from_private_payload


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


def test_extract_collection_id_from_saved_url() -> None:
    url = 'https://www.instagram.com/amir_razagh/saved/content-gg/18041740820703793/'
    assert extract_collection_id(url) == '18041740820703793'


def test_extract_reels_from_private_payload() -> None:
    payload = {
        'items': [
            {'media': {'code': 'AAA111', 'media_type': 2, 'product_type': 'clips'}},
            {'media': {'code': 'BBB222', 'media_type': 1, 'product_type': 'feed'}},
            {'media': {'code': 'CCC333', 'video_versions': [{'id': 'x'}]}},
        ]
    }
    urls = _extract_reels_from_private_payload(payload)
    assert urls == [
        'https://www.instagram.com/reel/AAA111/',
        'https://www.instagram.com/reel/CCC333/',
    ]
