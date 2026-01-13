from ttseed.util import normalize_topic_url


def test_normalize_topic_url_strips_fragment_and_p():
    url = "https://example.org/viewtopic.php?t=10&p=99#p99"
    assert normalize_topic_url(url) == "https://example.org/viewtopic.php?t=10"


def test_normalize_topic_url_keeps_f_and_t():
    url = "https://example.org/viewtopic.php?f=7&t=10&sid=abc"
    assert normalize_topic_url(url) == "https://example.org/viewtopic.php?f=7&t=10"
