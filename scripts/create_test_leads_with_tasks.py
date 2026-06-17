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


REPORT_PATH = Path("test_reports/create_test_leads_with_tasks.json")


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


def find_pipeline() -> tuple[int | None, int | None]:
    response = server.amocrm_request("GET", "/api/v4/leads/pipelines", params={"limit": 250})
    if not response.get("ok"):
        raise RuntimeError(f"Cannot list pipelines: {response.get('data')}")
    pipelines = embedded(response, "pipelines")
    for pipeline in pipelines:
        if pipeline.get("name") == "Новые клиенты | Маркетинговое агентство":
            status_id = next(
                (
                    status.get("id")
                    for status in pipeline.get("_embedded", {}).get("statuses", [])
                    if status.get("name") in ("Получена новая заявка", "Проведена квалификация")
                ),
                None,
            )
            return pipeline.get("id"), status_id
    if pipelines:
        pipeline = pipelines[0]
        editable = [status for status in pipeline.get("_embedded", {}).get("statuses", []) if status.get("is_editable")]
        return pipeline.get("id"), editable[0].get("id") if editable else None
    return None, None


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_codex_env()
    count = int(os.environ.get("AMOCRM_TEST_LEADS_COUNT", "20"))
    overdue_count = int(os.environ.get("AMOCRM_TEST_OVERDUE_TASKS_COUNT", str(count // 2)))
    chunk_size = int(os.environ.get("AMOCRM_BATCH_CHUNK_SIZE", "50"))
    suffix = time.strftime("%Y%m%d-%H%M%S")
    now = int(time.time())

    report: dict[str, Any] = {
        "ok": False,
        "count": count,
        "overdue_count": overdue_count,
        "future_count": count - overdue_count,
        "chunk_size": chunk_size,
        "created": [],
    }

    account = server.amocrm_request("GET", "/api/v4/account")
    if not account.get("ok"):
        raise RuntimeError(f"Cannot access account: {account.get('data')}")
    report["account"] = {"id": account["data"].get("id"), "name": account["data"].get("name")}

    pipeline_id, status_id = find_pipeline()
    report["pipeline_id"] = pipeline_id
    report["status_id"] = status_id

    leads_payload = []
    for index in range(1, count + 1):
        payload: dict[str, Any] = {
            "name": f"MCP Batch Test Deal {suffix} #{index:02d}",
            "price": 10000 + index * 1000,
            "_embedded": {
                "tags": [
                    {"name": "MCP batch test"},
                    {"name": "task overdue" if index <= overdue_count else "task future"},
                ]
            },
        }
        if pipeline_id:
            payload["pipeline_id"] = pipeline_id
        if status_id:
            payload["status_id"] = status_id
        leads_payload.append(payload)

    leads_result = server.batch_request("POST", "/api/v4/leads", leads_payload, chunk_size)
    report["leads_result"] = {
        "ok": leads_result["ok"],
        "chunks_processed": leads_result["chunks_processed"],
        "processed_items": leads_result["processed_items"],
    }
    if not leads_result["ok"]:
        report["lead_errors"] = leads_result["responses"]
        save_report(report)
        raise RuntimeError("Lead batch create failed")

    leads = leads_result["items"]
    tasks_payload = []
    for index, lead in enumerate(leads, 1):
        overdue = index <= overdue_count
        complete_till = now - index * 86400 if overdue else now + (index - overdue_count) * 86400
        tasks_payload.append(
            {
                "text": f"{'Просроченная' if overdue else 'Будущая'} batch-задача #{index:02d} по сделке",
                "complete_till": complete_till,
                "entity_id": lead["id"],
                "entity_type": "leads",
            }
        )

    tasks_result = server.batch_request("POST", "/api/v4/tasks", tasks_payload, chunk_size)
    report["tasks_result"] = {
        "ok": tasks_result["ok"],
        "chunks_processed": tasks_result["chunks_processed"],
        "processed_items": tasks_result["processed_items"],
    }
    report["created"] = [
        {
            "lead_id": lead.get("id"),
            "lead_name": lead.get("name"),
            "task_id": task.get("id") if index < len(tasks_result["items"]) else None,
            "task_kind": "overdue" if index < overdue_count else "future",
        }
        for index, (lead, task) in enumerate(zip(leads, tasks_result["items"]))
    ]
    report["ok"] = leads_result["ok"] and tasks_result["ok"] and len(tasks_result["items"]) == len(leads)
    if not tasks_result["ok"]:
        report["task_errors"] = tasks_result["responses"]

    save_report(report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "created_leads": len(leads),
                "created_tasks": len(tasks_result["items"]),
                "lead_chunks": leads_result["chunks_processed"],
                "task_chunks": tasks_result["chunks_processed"],
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
