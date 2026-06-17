from __future__ import annotations

import json
import os
import sys
import time
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amocrm_mcp import server  # noqa: E402


REPORT_PATH = Path("test_reports/communication_fact_pipeline_test.json")
ALLOWED_COLORS = {
    "#fffeb2",
    "#fffd7f",
    "#fff000",
    "#ffeab2",
    "#ffdc7f",
    "#ffce5a",
    "#ffdbdb",
    "#ffc8c8",
    "#ff8f92",
    "#d6eaff",
    "#c1e0ff",
    "#98cbff",
    "#ebffb1",
    "#deff81",
    "#87f2c0",
    "#f9deff",
    "#f3beff",
    "#ccc8f9",
    "#eb93ff",
    "#f2f3f4",
    "#e6e8ea",
}


def load_codex_env() -> None:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    env = config.get("mcp_servers", {}).get("amocrm", {}).get("env", {})
    if isinstance(env, dict):
        for key, value in env.items():
            os.environ.setdefault(key, str(value))


def embedded(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    value = data.get("_embedded", {}).get(key, [])
    return value if isinstance(value, list) else []


def call(label: str, method: str, path: str, params: dict[str, Any] | None = None, body: Any | None = None) -> dict[str, Any]:
    response = server.amocrm_request(method, path, params=params, body=body)
    print(f"{label}: HTTP {response.get('status')} ok={response.get('ok')}")
    REPORT["steps"][label] = {
        "ok": response.get("ok"),
        "status": response.get("status"),
        "path": response.get("url", "").split(".amocrm.ru", 1)[-1],
    }
    if not response.get("ok"):
        REPORT["failed_step"] = label
        REPORT["failure"] = response.get("data")
        save_report()
        raise RuntimeError(f"{label} failed: {response.get('data')}")
    return response


def save_report() -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_codex_env()
    missing = [key for key in ("AMOCRM_BASE_URL", "AMOCRM_LONG_LIVED_TOKEN") if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")

    suffix = time.strftime("%Y%m%d-%H%M%S")
    pipeline_name = f"Тест коммуникация-факт | {suffix}"
    statuses = [
        {"name": "Получен новый лид", "sort": 10, "color": "#fffeb2"},
        {"name": "Проведена квалификация", "sort": 20, "color": "#ffdc7f"},
        {"name": "Назначена встреча", "sort": 30, "color": "#d6eaff"},
        {"name": "Проведена встреча", "sort": 40, "color": "#c1e0ff"},
        {"name": "Отправлено КП", "sort": 50, "color": "#98cbff"},
        {"name": "Согласован старт", "sort": 60, "color": "#deff81"},
        {"name": "Передан в производство", "sort": 70, "color": "#87f2c0"},
    ]

    assert all(status["color"] in ALLOWED_COLORS for status in statuses)
    REPORT["pipeline_name"] = pipeline_name
    REPORT["expected_statuses"] = statuses

    call("account.get", "GET", "/api/v4/account")
    created = call(
        "pipeline.create",
        "POST",
        "/api/v4/leads/pipelines",
        body=[
            {
                "name": pipeline_name,
                "is_main": False,
                "is_unsorted_on": True,
                "sort": 130,
                "_embedded": {"statuses": statuses},
            }
        ],
    )
    pipeline = embedded(created, "pipelines")[0]
    pipeline_id = int(pipeline["id"])
    REPORT["pipeline_id"] = pipeline_id

    fetched = call("pipeline.get", "GET", f"/api/v4/leads/pipelines/{pipeline_id}")
    fetched_statuses = fetched["data"]["_embedded"]["statuses"]
    custom = [status for status in fetched_statuses if status.get("is_editable")]
    by_name = {status["name"]: status for status in custom}
    errors = []
    for expected in statuses:
        actual = by_name.get(expected["name"])
        if not actual:
            errors.append({"status": expected["name"], "error": "missing"})
            continue
        if actual.get("color", "").lower() != expected["color"]:
            errors.append({"status": expected["name"], "expected": expected["color"], "actual": actual.get("color")})
        if actual.get("color", "").lower() not in ALLOWED_COLORS:
            errors.append({"status": expected["name"], "error": "color not in whitelist", "actual": actual.get("color")})

    REPORT["actual_statuses"] = [
        {"id": status.get("id"), "name": status.get("name"), "sort": status.get("sort"), "color": status.get("color")}
        for status in custom
    ]
    REPORT["errors"] = errors
    REPORT["ok"] = not errors
    save_report()
    if errors:
        raise RuntimeError(f"Verification failed: {errors}")
    print(json.dumps({"ok": True, "pipeline_id": pipeline_id, "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
    return 0


REPORT: dict[str, Any] = {"ok": False, "steps": {}}


if __name__ == "__main__":
    raise SystemExit(main())
