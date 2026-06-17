from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "amocrm-account-manager"
PLUGINS_ROOT = Path.home() / "plugins"
TARGET = PLUGINS_ROOT / PLUGIN_NAME
MARKETPLACE_PATH = Path.home() / ".agents" / "plugins" / "marketplace.json"

EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "test_reports", "build", "dist"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def copy_plugin() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    for source in ROOT.rglob("*"):
        if should_skip(source):
            continue
        rel = source.relative_to(ROOT)
        destination = TARGET / rel
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def marketplace_entry() -> dict:
    return {
        "name": PLUGIN_NAME,
        "source": {
            "source": "local",
            "path": f"./plugins/{PLUGIN_NAME}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def update_marketplace() -> None:
    MARKETPLACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MARKETPLACE_PATH.exists():
        data = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))
    else:
        data = {
            "name": "personal",
            "interface": {"displayName": "Personal"},
            "plugins": [],
        }

    data.setdefault("name", "personal")
    data.setdefault("interface", {"displayName": "Personal"})
    data.setdefault("plugins", [])
    entry = marketplace_entry()
    plugins = [plugin for plugin in data["plugins"] if plugin.get("name") != PLUGIN_NAME]
    plugins.append(entry)
    data["plugins"] = plugins
    MARKETPLACE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    copy_plugin()
    update_marketplace()
    print(json.dumps({"plugin_path": str(TARGET), "marketplace_path": str(MARKETPLACE_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
