from unittest.mock import MagicMock, patch

import pytest

from app.copywriter import generate_copy


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
