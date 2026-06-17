from __future__ import annotations

import json
import os
import random
import sys
import time
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amocrm_mcp import server  # noqa: E402


REPORT_PATH = Path("test_reports/create_bulk_test_deals.json")
SAFE_FIELD_TYPES = {
    "text",
    "numeric",
    "checkbox",
    "select",
    "multiselect",
    "date",
    "url",
    "date_time",
    "textarea",
    "radiobutton",
    "streetaddress",
    "birthday",
}
TAGS = [
    "MCP bulk test",
    "SEO",
    "SMM",
    "Performance",
    "Ретейнер",
    "Высокий бюджет",
    "Нужен бриф",
    "Кейс/портфолио отправлено",
    "Inbound",
    "Referral",
]
SERVICES = ["SEO", "Контекстная реклама", "Таргетированная реклама", "SMM", "Контент-маркетинг", "Аналитика"]
INDUSTRIES = ["E-commerce", "SaaS/IT", "Недвижимость", "Медицина", "Образование", "B2B услуги", "HoReCa"]


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


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def find_pipeline() -> tuple[int | None, list[int]]:
    response = server.amocrm_request("GET", "/api/v4/leads/pipelines", params={"limit": 250})
    if not response.get("ok"):
        raise RuntimeError(f"Cannot list pipelines: {response.get('data')}")

    pipelines = embedded(response, "pipelines")
    preferred = next((item for item in pipelines if item.get("name") == "Новые клиенты | Маркетинговое агентство"), None)
    pipeline = preferred or (pipelines[0] if pipelines else None)
    if not pipeline:
        return None, []
    statuses = [
        int(status["id"])
        for status in pipeline.get("_embedded", {}).get("statuses", [])
        if status.get("is_editable") and status.get("id")
    ]
    return int(pipeline["id"]), statuses


def load_lead_fields() -> list[dict[str, Any]]:
    response = server.amocrm_request("GET", "/api/v4/leads/custom_fields", params={"limit": 250})
    if not response.get("ok"):
        raise RuntimeError(f"Cannot list lead fields: {response.get('data')}")
    return [field for field in embedded(response, "custom_fields") if field.get("type") in SAFE_FIELD_TYPES]


def enum_value(field: dict[str, Any], index: int | None = None) -> dict[str, Any] | None:
    enums = field.get("enums") or []
    if not enums:
        return None
    enum = enums[index % len(enums) if index is not None else random.randrange(len(enums))]
    value: dict[str, Any] = {"value": enum.get("value")}
    if enum.get("id"):
        value["enum_id"] = enum["id"]
    return value


def value_for_field(field: dict[str, Any], deal_index: int) -> dict[str, Any] | None:
    field_type = field.get("type")
    name = str(field.get("name", ""))
    now = int(time.time())

    if field_type == "text":
        value = f"Тестовое значение {deal_index}"
    elif field_type == "numeric":
        value = random.randint(10, 999)
    elif field_type == "checkbox":
        value = random.choice([True, False])
    elif field_type in {"select", "radiobutton"}:
        selected = enum_value(field, deal_index)
        return {"field_id": field["id"], "values": [selected]} if selected else None
    elif field_type == "multiselect":
        enums = field.get("enums") or []
        if not enums:
            return None
        count = random.randint(1, min(3, len(enums)))
        values = []
        for enum in random.sample(enums, count):
            item: dict[str, Any] = {"value": enum.get("value")}
            if enum.get("id"):
                item["enum_id"] = enum["id"]
            values.append(item)
        return {"field_id": field["id"], "values": values}
    elif field_type in {"date", "birthday"}:
        value = now + random.randint(1, 90) * 86400
    elif field_type == "date_time":
        value = now + random.randint(1, 14) * 86400 + random.randint(9, 18) * 3600
    elif field_type == "url":
        value = f"https://example.com/test-deal-{deal_index}"
    elif field_type == "textarea":
        value = f"Сгенерированный тестовый бриф по сделке {deal_index}: цель, бюджет, канал, KPI."
    elif field_type == "streetaddress":
        value = f"Тестовая улица, дом {deal_index}"
    else:
        return None

    if "Услуги интереса" in name:
        return {"field_id": field["id"], "values": [{"value": random.choice(SERVICES)}]}
    return {"field_id": field["id"], "values": [{"value": value}]}


def custom_values_for_deal(fields: list[dict[str, Any]], deal_index: int) -> list[dict[str, Any]]:
    if not fields:
        return []
    selected = random.sample(fields, min(random.randint(2, 7), len(fields)))
    values = []
    for field in selected:
        value = value_for_field(field, deal_index)
        if value:
            values.append(value)
    return values


def make_deal_payloads(count: int, fields: list[dict[str, Any]], pipeline_id: int | None, status_ids: list[int]) -> list[dict[str, Any]]:
    suffix = time.strftime("%Y%m%d-%H%M%S")
    payloads: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        industry = random.choice(INDUSTRIES)
        payload: dict[str, Any] = {
            "name": f"MCP Bulk Deal {suffix} #{index:03d} | {industry}",
            "price": random.choice([50000, 90000, 120000, 180000, 250000, 420000, 600000]),
            "_embedded": {"tags": [{"name": tag} for tag in random.sample(TAGS, random.randint(2, 4))]},
        }
        if pipeline_id:
            payload["pipeline_id"] = pipeline_id
        if status_ids:
            payload["status_id"] = random.choice(status_ids)
        custom_values = custom_values_for_deal(fields, index)
        if custom_values:
            payload["custom_fields_values"] = custom_values
        payloads.append(payload)
    return payloads


def make_task_payloads(leads: list[dict[str, Any]], max_tasks_per_deal: int) -> tuple[list[dict[str, Any]], dict[int, int]]:
    now = int(time.time())
    payloads: list[dict[str, Any]] = []
    counts: dict[int, int] = {}
    for lead in leads:
        task_count = random.randint(0, max_tasks_per_deal)
        counts[int(lead["id"])] = task_count
        for task_index in range(1, task_count + 1):
            payloads.append(
                {
                    "text": random.choice(
                        [
                            "Уточнить бюджет и сроки",
                            "Подготовить КП",
                            "Проверить статус согласования",
                            "Назначить встречу",
                            "Отправить кейсы",
                        ]
                    )
                    + f" #{task_index}",
                    "complete_till": now + random.randint(1, 21) * 86400,
                    "entity_id": lead["id"],
                    "entity_type": "leads",
                }
            )
    return payloads, counts


def main() -> int:
    load_codex_env()
    os.environ["AMOCRM_READONLY"] = "false"
    os.environ.pop("AMOCRM_WRITE_ALLOWLIST", None)
    os.environ.pop("AMOCRM_WRITE_DENYLIST", None)
    os.environ.setdefault("AMOCRM_TIMEOUT", "90")

    count = int(os.environ.get("AMOCRM_BULK_DEALS_COUNT", "500"))
    chunk_size = int(os.environ.get("AMOCRM_BATCH_CHUNK_SIZE", "50"))
    max_tasks_per_deal = int(os.environ.get("AMOCRM_MAX_TASKS_PER_DEAL", "3"))
    seed = int(os.environ.get("AMOCRM_BULK_RANDOM_SEED", str(int(time.time()))))
    random.seed(seed)

    report: dict[str, Any] = {
        "ok": False,
        "count": count,
        "chunk_size": chunk_size,
        "max_tasks_per_deal": max_tasks_per_deal,
        "seed": seed,
    }

    account = server.amocrm_request("GET", "/api/v4/account")
    if not account.get("ok"):
        raise RuntimeError(f"Cannot access account: {account.get('data')}")
    report["account"] = {"id": account["data"].get("id"), "name": account["data"].get("name")}

    pipeline_id, status_ids = find_pipeline()
    fields = load_lead_fields()
    report["pipeline_id"] = pipeline_id
    report["status_ids_count"] = len(status_ids)
    report["usable_fields_count"] = len(fields)

    deals_payload = make_deal_payloads(count, fields, pipeline_id, status_ids)
    leads_result = server.batch_request("POST", "/api/v4/leads", deals_payload, chunk_size)
    report["leads_result"] = {
        "ok": leads_result["ok"],
        "chunks_processed": leads_result["chunks_processed"],
        "processed_items": leads_result["processed_items"],
        "created_items": len(leads_result["items"]),
    }
    if not leads_result["ok"]:
        report["lead_errors"] = leads_result["responses"]
        save_report(report)
        raise RuntimeError("Lead batch create failed")

    task_payloads, task_counts = make_task_payloads(leads_result["items"], max_tasks_per_deal)
    tasks_result = server.batch_request("POST", "/api/v4/tasks", task_payloads, chunk_size) if task_payloads else {
        "ok": True,
        "chunks_processed": 0,
        "processed_items": 0,
        "items": [],
        "responses": [],
    }
    report["tasks_result"] = {
        "ok": tasks_result["ok"],
        "chunks_processed": tasks_result["chunks_processed"],
        "processed_items": tasks_result["processed_items"],
        "created_items": len(tasks_result["items"]),
    }
    report["task_distribution"] = {
        "deals_with_0_tasks": sum(1 for count_value in task_counts.values() if count_value == 0),
        "deals_with_1_task": sum(1 for count_value in task_counts.values() if count_value == 1),
        "deals_with_2_tasks": sum(1 for count_value in task_counts.values() if count_value == 2),
        "deals_with_3_tasks": sum(1 for count_value in task_counts.values() if count_value == 3),
    }
    if not tasks_result["ok"]:
        report["task_errors"] = tasks_result["responses"]

    report["sample_lead_ids"] = [item["id"] for item in leads_result["items"][:20]]
    report["ok"] = leads_result["ok"] and tasks_result["ok"] and len(leads_result["items"]) == count
    save_report(report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "created_deals": len(leads_result["items"]),
                "created_tasks": len(tasks_result["items"]),
                "deal_chunks": leads_result["chunks_processed"],
                "task_chunks": tasks_result["chunks_processed"],
                "task_distribution": report["task_distribution"],
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
