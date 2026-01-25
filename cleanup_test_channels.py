#!/usr/bin/env python3
"""Cleanup and normalize test_channels in bot_data.json."""
import json
import re
from pathlib import Path

DB_NAME = "bot_data.json"


def normalize_channel_username(raw_username: str) -> str | None:
    if not raw_username:
        return None

    name = str(raw_username).strip()
    if not name:
        return None

    # Remove markdown links like (https://t.me/...)
    name = re.sub(r"\(https?://t\.me/[^)]+\)", "", name, flags=re.IGNORECASE)

    # Remove square brackets
    name = name.replace("[", "").replace("]", "")

    name = name.strip()
    if not name:
        return None

    # Remove leading @ and any invalid characters
    name = name.lstrip("@")
    name = re.sub(r"[^A-Za-z0-9_]", "", name)

    if not name:
        return None

    return f"@{name.upper()}"


def main() -> None:
    db_path = Path(DB_NAME)
    if not db_path.exists():
        print(f"❌ {DB_NAME} not found")
        return

    try:
        with db_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"❌ Failed to load {DB_NAME}: {exc}")
        return

    raw_test_channels = data.get("test_channels", [])
    cleaned = []
    seen = set()
    for ch in raw_test_channels:
        norm = normalize_channel_username(ch)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(norm)

    data["test_channels"] = cleaned

    try:
        with db_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Cleaned test_channels: {len(raw_test_channels)} -> {len(cleaned)}")
    except Exception as exc:
        print(f"❌ Failed to save {DB_NAME}: {exc}")


if __name__ == "__main__":
    main()
