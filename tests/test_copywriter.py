from unittest.mock import MagicMock, patch

import pytest

from app.copywriter import generate_copy, _is_reasoning_model


@pytest.mark.parametrize("model,expected", [
    ("kimi-k2.6", True),
    ("kimi-k2", True),
    ("KIMI-K2.7-CODE", True),
    ("moonshot-v1-auto", False),
    ("moonshot-v1-8k", False),
    ("gpt-4o", False),
])
def test_is_reasoning_model(model, expected):
    assert _is_reasoning_model(model) is expected


def test_generate_copy_parses_json_response(sample_copy):
    fake_json = """
    {
      "caption": "When Monday hits and you forgot it was a holiday 💀 #monday",
      "hook": "POV: the alarm was lying",
      "overlay_lines": ["ME ON MONDAY", "ALSO ME:"]
    }
    """
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=fake_json))]
    )
    with patch("app.copywriter.OpenAI", return_value=mock_client):
        result = generate_copy(
            topic="Monday motivation, gym",
            tone="funny",
            overlay_slot_count=2,
            api_key="fake-key",
            model="kimi-k2",
        )
    assert result.overlay_lines == ["ME ON MONDAY", "ALSO ME:"]
    assert result.hook == "POV: the alarm was lying"
    assert "#monday" in result.caption


def test_generate_copy_raises_on_bad_json():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not json"))]
    )
    with patch("app.copywriter.OpenAI", return_value=mock_client):
        with pytest.raises(ValueError):
            generate_copy(
                topic="x", tone="funny", overlay_slot_count=2,
                api_key="fake-key", model="kimi-k2",
            )


def test_normalize_recovers_char_split_lines():
    """If the model spells a phrase one char per element, merge it back."""
    from app.copywriter import _normalize_overlay_lines
    raw = ["P", "o", "w", "e", "r", " ", "t", "h", "r", "o", "u", "g", "h"]
    assert _normalize_overlay_lines(raw) == ["Power through"]


def test_normalize_wraps_bare_string():
    """A string (not array) must NOT be split into characters by list()."""
    from app.copywriter import _normalize_overlay_lines
    assert _normalize_overlay_lines("Me on Monday") == ["Me on Monday"]


def test_normalize_preserves_real_phrases():
    """Genuine multi-element arrays are returned unchanged."""
    from app.copywriter import _normalize_overlay_lines
    assert _normalize_overlay_lines(["ME ON MONDAY", "ALSO ME"]) == ["ME ON MONDAY", "ALSO ME"]
