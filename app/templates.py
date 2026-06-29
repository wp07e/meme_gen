"""Load and validate JSON template layout specs."""
import json
from pathlib import Path

from pydantic import BaseModel, field_validator

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TextPosition(BaseModel):
    x: str  # "center" or pixel int
    y: str  # "bottom-60" / "top-60" or pixel int

    @field_validator("x", "y", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        # Accept raw ints in JSON (e.g. 60) and normalize to "60".
        return str(v) if isinstance(v, int) and not isinstance(v, bool) else v


class OverlayRef(BaseModel):
    file: str  # filename in assets/
    x: int = 0
    y: int = 0


class TemplateSpec(BaseModel):
    name: str
    description: str
    aspect_ratio: str  # "1:1" | "9:16"
    width: int
    height: int
    font: str
    font_size: int
    font_color: str
    stroke_color: str
    stroke_width: int
    positions: dict[str, TextPosition]
    overlays: list[OverlayRef] = []


def load_template(name: str) -> TemplateSpec:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No template named '{name}' at {path}")
    data = json.loads(path.read_text())
    return TemplateSpec(**data)


def list_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))
