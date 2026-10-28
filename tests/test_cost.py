import pytest

import config
import cost


def test_token_price_with_cached_input():
    usage = {"input_tokens": 1_000_000, "input_tokens_details": {"cached_tokens": 400_000}, "output_tokens": 100_000}
    assert cost.usd("muse-spark-1.3", usage) == pytest.approx(0.6 * 1.25 + 0.4 * 0.15 + 0.1 * 4.25)


def test_sam_and_transcribe_prices():
    assert cost.usd("sam-3.1", {"images_processed": 4}) == pytest.approx(0.01)
    assert cost.usd("sam-3.1", {"video_frames_processed": 10}) == pytest.approx(50 * 0.0002)
    assert cost.usd("muse-voice-transcribe-1.0", {"audio_s": 3600}) == pytest.approx(0.18)


def test_budget_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COST_LEDGER", tmp_path / "costs.jsonl")
    monkeypatch.setattr(config, "MAX_SPEND_USD", 0.01)
    cost.check_budget()
    cost.record("sam-3.1", "heal", {"images_processed": 4}, 100)
    assert cost.by_purpose() == {"heal": pytest.approx(0.01)}
    with pytest.raises(cost.BudgetExceeded):
        cost.check_budget()
