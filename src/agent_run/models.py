from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelProfile:
    name: str
    cheap: str
    strong: str
    judge: str
    coder_temperature: float = 0.1


DEFAULT_PROFILE = ModelProfile(
    name="default",
    # Prefer currently listed OpenRouter slugs (avoid retired / rate-limited IDs).
    cheap="~deepseek/deepseek-flash-latest",
    strong="openai/gpt-4o-mini",
    judge="google/gemini-2.5-flash",
    coder_temperature=0.1,
)


def _parse_simple_yaml_profile(text: str, name: str) -> ModelProfile | None:
    """Minimal parser for the documented models.yaml shape."""
    in_profile = False
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("#") or not line.strip():
            continue
        if line.startswith("profiles:"):
            continue
        if re.match(rf"^  {re.escape(name)}:\s*$", line):
            in_profile = True
            continue
        if in_profile and re.match(r"^  \w", line) and not line.startswith("    "):
            break
        if in_profile:
            m = re.match(r"^\s+(\w+):\s*(.+)\s*$", line)
            if m:
                data[m.group(1)] = m.group(2).strip().strip("\"'")
    if not data:
        return None
    return ModelProfile(
        name=name,
        cheap=data.get("cheap", DEFAULT_PROFILE.cheap),
        strong=data.get("strong", DEFAULT_PROFILE.strong),
        judge=data.get("judge", DEFAULT_PROFILE.judge),
        coder_temperature=float(data.get("coder_temperature", DEFAULT_PROFILE.coder_temperature)),
    )


def load_profile(name: str = "default") -> ModelProfile:
    path = os.environ.get("AGENT_RUN_MODELS_FILE")
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path.home() / ".config" / "agent-run" / "models.yaml")
    for candidate in candidates:
        if candidate.is_file():
            parsed = _parse_simple_yaml_profile(candidate.read_text(encoding="utf-8"), name)
            if parsed:
                return parsed
    if name != "default":
        p = DEFAULT_PROFILE
        return ModelProfile(name, p.cheap, p.strong, p.judge, p.coder_temperature)
    return DEFAULT_PROFILE


def coder_model(profile: ModelProfile, iteration: int, force_strong: bool) -> str:
    if force_strong or iteration >= 4:
        return profile.strong
    return profile.cheap
