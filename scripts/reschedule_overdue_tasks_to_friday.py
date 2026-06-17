from __future__ import annotations

import json
import os
import sys
import time
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amocrm_mcp import server  # noqa: E402


REPORT_PATH = Path("test_reports/reschedule_overdue_tasks_to_friday.json")
LOCAL_TZ = ZoneInfo(os.environ.get("AMOCRM_LOCAL_TIMEZONE", "Asia/Vladivostok"))


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


def next_friday_timestamp(hour: int = 18, minute: int = 0) -> tuple[int, str]:
    now = datetime.now(LOCAL_TZ)
    days_until_friday = (4 - now.weekday()) % 7
    if days_until_friday == 0 and (now.hour, now.minute) >= (hour, minute):
        days_until_friday = 7
    target = (now + timedelta(days=days_until_friday)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return int(target.timestamp()), target.isoformat()


def list_all_open_overdue_tasks(now_ts: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for page in range(1, 51):
        response = server.amocrm_request(
            "GET",
            "/api/v4/tasks",
            params={
                "page": page,
                "limit": 250,
                "filter[is_completed]": 0,
                "filter[complete_till][to]": now_ts - 1,
            },
        )
        if not response.get("ok"):
            raise RuntimeError(f"Cannot list overdue tasks: {response.get('data')}")
        page_tasks = embedded(response, "tasks")
        tasks.extend(page_tasks)
        data = response.get("data")
        links = data.get("_links", {}) if isinstance(data, dict) else {}
        if not isinstance(links, dict) or "next" not in links:
            break
    return tasks


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_codex_env()
    os.environ.setdefault("AMOCRM_TIMEOUT", "90")
    now_ts = int(time.time())
    friday_ts, friday_iso = next_friday_timestamp()
    report: dict[str, Any] = {
        "ok": False,
        "now": datetime.now(LOCAL_TZ).isoformat(),
        "target_friday": friday_iso,
        "target_complete_till": friday_ts,
    }

    overdue_tasks = [
        task
        for task in list_all_open_overdue_tasks(now_ts)
        if task.get("entity_type") == "leads" and task.get("entity_id")
    ]
    report["overdue_lead_tasks_found"] = len(overdue_tasks)
    report["task_ids"] = [task.get("id") for task in overdue_tasks]
    report["lead_ids"] = sorted({task.get("entity_id") for task in overdue_tasks})

    if not overdue_tasks:
        report["ok"] = True
        save_report(report)
        print(json.dumps({"ok": True, "message": "No overdue lead tasks found", "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
        return 0

    task_updates = [{"id": task["id"], "complete_till": friday_ts} for task in overdue_tasks]
    tasks_result = server.batch_request("PATCH", "/api/v4/tasks", task_updates, chunk_size=50)
    report["tasks_update"] = {
        "ok": tasks_result["ok"],
        "processed_items": tasks_result["processed_items"],
        "chunks_processed": tasks_result["chunks_processed"],
        "responses": tasks_result["responses"],
    }
    if not tasks_result["ok"]:
        save_report(report)
        raise RuntimeError("Task batch update failed")

    note_text = (
        f"Просроченная задача перенесена на пятницу {datetime.fromtimestamp(friday_ts, LOCAL_TZ).strftime('%d.%m.%Y %H:%M')} "
        "через batch-тест amoCRM MCP."
    )
    notes_payload = [
        {
            "entity_id": lead_id,
            "note_type": "common",
            "params": {"text": note_text},
        }
        for lead_id in report["lead_ids"]
    ]
    notes_result = server.batch_request("POST", "/api/v4/leads/notes", notes_payload, chunk_size=50)
    report["notes_create"] = {
        "ok": notes_result["ok"],
        "processed_items": notes_result["processed_items"],
        "chunks_processed": notes_result["chunks_processed"],
        "responses": notes_result["responses"],
    }
    if not notes_result["ok"]:
        save_report(report)
        raise RuntimeError("Notes batch create failed")

    verified: list[dict[str, Any]] = []
    for task_chunk in server.chunked([task["id"] for task in overdue_tasks], 10):
        verify_response = server.amocrm_request(
            "GET",
            "/api/v4/tasks",
            params={"limit": 250, "filter[id][]": task_chunk},
        )
        if verify_response.get("ok"):
            verified.extend(embedded(verify_response, "tasks"))
    report["verified_tasks"] = [
        {
            "id": task.get("id"),
            "entity_id": task.get("entity_id"),
            "complete_till": task.get("complete_till"),
            "moved_to_target": task.get("complete_till") == friday_ts,
        }
        for task in verified
    ]
    report["ok"] = all(task["moved_to_target"] for task in report["verified_tasks"]) and len(report["verified_tasks"]) == len(overdue_tasks)
    save_report(report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "overdue_tasks_moved": len(overdue_tasks),
                "deals_noted": len(report["lead_ids"]),
                "target_friday": friday_iso,
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
