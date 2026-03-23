from app.services.analysis import (
    FEASIBILITY_ALLOWED,
    RECORDING_TIME_ALLOWED,
    VIRALITY_ALLOWED,
    parse_and_normalize_analysis,
)


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


def test_parse_and_normalize_analysis_outputs_sheet_dropdown_values() -> None:
    raw = '''
    {
      "concept": "late-night coding confession",
      "script": "show desk setup, then punchline about deadlines",
      "requirements": "Laptop, hoodie",
      "virality": "medium",
      "feasibility": "hard",
      "recording_time": "about 20 minutes"
    }
    '''

    result = parse_and_normalize_analysis(raw)
    assert result.virality in VIRALITY_ALLOWED
    assert result.feasibility in FEASIBILITY_ALLOWED
    assert result.recording_time in RECORDING_TIME_ALLOWED
    assert result.virality == 'Mid'
    assert result.feasibility == 'Complex'
    assert result.recording_time == '10-30'
