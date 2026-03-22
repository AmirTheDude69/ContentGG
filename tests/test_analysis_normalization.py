from app.services.analysis import parse_and_normalize_analysis


def test_parse_and_normalize_analysis_maps_enums() -> None:
    raw = '''
    {
      "concept": "date with vibecoder founder",
      "script": "open with awkward outfit check",
      "requirements": "Outfit\\nWallet\\nCafe",
      "virality": "very high",
      "feasibility": "simple",
      "recording_time": "under 5 minutes"
    }
    '''

    result = parse_and_normalize_analysis(raw)
    assert result.virality == 'High'
    assert result.feasibility == 'Easy'
    assert result.recording_time == '<5'
    assert result.requirements == 'Outfit, Wallet, Cafe'
