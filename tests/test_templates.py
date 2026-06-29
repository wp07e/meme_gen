import pytest

from app.templates import TemplateSpec, load_template, list_templates


def test_load_template_returns_spec():
    spec = load_template("caption-top-bottom")
    assert isinstance(spec, TemplateSpec)
    assert spec.name == "caption-top-bottom"
    assert spec.width == 1080
    assert spec.aspect_ratio == "1:1"


def test_load_template_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("app.templates.TEMPLATES_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_template("does-not-exist")


def test_list_templates_includes_known():
    names = list_templates()
    assert "caption-top-bottom" in names
