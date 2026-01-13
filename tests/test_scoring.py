from ttseed.scoring import compute_score, vulnerability_key


def test_vulnerability_key_prefers_low_seeders():
    low_seed = vulnerability_key(0, 5, None, None, 100)
    high_seed = vulnerability_key(5, 5, None, None, 100)
    assert low_seed < high_seed


def test_compute_score_returns_float():
    score = compute_score(2, 10, None, None, 1024)
    assert isinstance(score, float)
