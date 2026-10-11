"""Edit .env in place: keeps comments and order, appends unknown keys at the end."""

from __future__ import annotations

import re
from pathlib import Path

from analitik_importa.config import ROOT_DIR, get_settings

ENV_PATH = ROOT_DIR / ".env"
_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _format(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(ch in text for ch in " #\"'"):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def update_env(values: dict[str, object], path: Path = ENV_PATH) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = {k.upper(): v for k, v in values.items()}
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        key = m.group(1).upper() if m else None
        if key in pending:
            out.append(f"{key}={_format(pending.pop(key))}")
        else:
            out.append(line)
    if pending:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{k}={_format(v)}" for k, v in pending.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    get_settings.cache_clear()
