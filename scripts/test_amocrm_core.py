from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amocrm_mcp import server


REPORT_PATH = Path("test_reports/amocrm_core_test.json")


class StepFailed(RuntimeError):
    def __init__(self, label: str, response: dict[str, Any]):
        super().__init__(label)
        self.label = label
        self.response = response


def embedded(response: dict[str, Any], name: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    value = data.get("_embedded", {}).get(name, [])
    return value if isinstance(value, list) else []


def summarize_response(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    summary: dict[str, Any] = {
        "ok": response.get("ok"),
        "status": response.get("status"),
        "url_path": response.get("url", "").split(".amocrm.ru", 1)[-1],
    }
    if isinstance(data, dict):
        summary["top_keys"] = sorted(data.keys())[:12]
        if "id" in data:
            summary["id"] = data["id"]
        if "name" in data:
            summary["name"] = data["name"]
        if "_embedded" in data and isinstance(data["_embedded"], dict):
            summary["embedded_counts"] = {
                key: len(value) for key, value in data["_embedded"].items() if isinstance(value, list)
            }
        if "title" in data or "detail" in data:
            summary["problem"] = {key: data.get(key) for key in ("title", "detail", "type") if key in data}
    else:
        summary["data_type"] = type(data).__name__
    return summary


def call(label: str, method: str, path: str, params: dict[str, Any] | None = None, body: Any | None = None) -> dict[str, Any]:
    response = server.amocrm_request(method, path, params=params, body=body)
    REPORT["steps"][label] = summarize_response(response)
    print(f"{label}: HTTP {response.get('status')} ok={response.get('ok')}")
    if not response.get("ok"):
        raise StepFailed(label, response)
    return response


def first_id(response: dict[str, Any], collection: str) -> int:
    items = embedded(response, collection)
    if not items or "id" not in items[0]:
        raise RuntimeError(f"Cannot extract id from {collection}")
    return int(items[0]["id"])


def first_item(response: dict[str, Any], collection: str) -> dict[str, Any]:
    items = embedded(response, collection)
    if not items:
        raise RuntimeError(f"Cannot extract item from {collection}")
    return items[0]


def first_editable_status(pipeline: dict[str, Any]) -> int | None:
    statuses = pipeline.get("_embedded", {}).get("statuses", [])
    for status in statuses:
        if status.get("is_editable") and status.get("id"):
            return int(status["id"])
    return None


def main() -> int:
    missing = [name for name in ("AMOCRM_BASE_URL", "AMOCRM_LONG_LIVED_TOKEN") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")

    suffix = time.strftime("%Y%m%d-%H%M%S")
    prefix = f"MCP Smoke {suffix}"
    REPORT["prefix"] = prefix
    REPORT["base_url"] = os.environ["AMOCRM_BASE_URL"]

    account = call("account.get", "GET", "/api/v4/account", {"with": "users_groups,task_types,version,datetime_settings"})
    REPORT["account"] = {
        "id": account["data"].get("id"),
        "name": account["data"].get("name"),
        "subdomain": account["data"].get("subdomain"),
    }

    users = call("users.list", "GET", "/api/v4/users", {"limit": 10})
    call("roles.list", "GET", "/api/v4/roles", {"limit": 10})

    pipeline = call(
        "pipelines.create",
        "POST",
        "/api/v4/leads/pipelines",
        body=[
            {
                "name": f"{prefix} Pipeline",
                "is_main": False,
                "is_unsorted_on": True,
                "sort": 50,
                "request_id": "pipeline",
                "_embedded": {
                    "statuses": [
                        {"name": "Новый запрос", "sort": 10, "color": "#fffeb2"},
                        {"name": "Диагностика", "sort": 20, "color": "#c1e0ff"},
                    ]
                },
            }
        ],
    )
    pipeline_item = first_item(pipeline, "pipelines")
    pipeline_id = int(pipeline_item["id"])
    status_id = first_editable_status(pipeline_item)
    REPORT["created"]["pipeline_id"] = pipeline_id
    REPORT["created"]["status_id"] = status_id

    call("pipelines.get", "GET", f"/api/v4/leads/pipelines/{pipeline_id}")
    call("pipelines.statuses.list", "GET", f"/api/v4/leads/pipelines/{pipeline_id}/statuses")

    extra_status = call(
        "pipelines.statuses.create",
        "POST",
        f"/api/v4/leads/pipelines/{pipeline_id}/statuses",
        body=[{"name": "Коммерческое предложение", "sort": 30, "color": "#deff81"}],
    )
    REPORT["created"]["extra_status_id"] = first_id(extra_status, "statuses")

    lead_field = call(
        "custom_fields.leads.create",
        "POST",
        "/api/v4/leads/custom_fields",
        body=[{"name": f"{prefix} Source", "type": "text", "sort": 20}],
    )
    contact_field = call(
        "custom_fields.contacts.create",
        "POST",
        "/api/v4/contacts/custom_fields",
        body=[{"name": f"{prefix} Messenger", "type": "text", "sort": 20}],
    )
    company_field = call(
        "custom_fields.companies.create",
        "POST",
        "/api/v4/companies/custom_fields",
        body=[{"name": f"{prefix} Segment", "type": "text", "sort": 20}],
    )
    lead_field_id = first_id(lead_field, "custom_fields")
    contact_field_id = first_id(contact_field, "custom_fields")
    company_field_id = first_id(company_field, "custom_fields")
    REPORT["created"].update(
        {
            "lead_field_id": lead_field_id,
            "contact_field_id": contact_field_id,
            "company_field_id": company_field_id,
        }
    )
    call("custom_fields.leads.list", "GET", "/api/v4/leads/custom_fields", {"limit": 50})

    tag = call("tags.leads.create", "POST", "/api/v4/leads/tags", body=[{"name": f"{prefix} Tag"}])
    tag_name = first_item(tag, "tags").get("name", f"{prefix} Tag")
    REPORT["created"]["tag_name"] = tag_name

    contact = call(
        "contacts.create",
        "POST",
        "/api/v4/contacts",
        body=[
            {
                "name": f"{prefix} Contact",
                "custom_fields_values": [
                    {"field_code": "PHONE", "values": [{"value": "+79990000000", "enum_code": "WORK"}]},
                    {"field_id": contact_field_id, "values": [{"value": "@mcp_smoke"}]},
                ],
            }
        ],
    )
    contact_id = first_id(contact, "contacts")
    REPORT["created"]["contact_id"] = contact_id

    company = call(
        "companies.create",
        "POST",
        "/api/v4/companies",
        body=[
            {
                "name": f"{prefix} Company",
                "custom_fields_values": [{"field_id": company_field_id, "values": [{"value": "integration"}]}],
            }
        ],
    )
    company_id = first_id(company, "companies")
    REPORT["created"]["company_id"] = company_id

    lead_payload: dict[str, Any] = {
        "name": f"{prefix} Lead",
        "price": 12345,
        "pipeline_id": pipeline_id,
        "custom_fields_values": [{"field_id": lead_field_id, "values": [{"value": "mcp-test"}]}],
        "_embedded": {
            "contacts": [{"id": contact_id}],
            "companies": [{"id": company_id}],
            "tags": [{"name": tag_name}],
        },
    }
    if status_id:
        lead_payload["status_id"] = status_id
    lead = call("leads.create", "POST", "/api/v4/leads", body=[lead_payload])
    lead_id = first_id(lead, "leads")
    REPORT["created"]["lead_id"] = lead_id

    call("leads.get", "GET", f"/api/v4/leads/{lead_id}", {"with": "contacts,companies"})
    call("contacts.get", "GET", f"/api/v4/contacts/{contact_id}", {"with": "leads"})
    call("companies.get", "GET", f"/api/v4/companies/{company_id}", {"with": "contacts,leads"})

    note = call(
        "notes.leads.create",
        "POST",
        f"/api/v4/leads/{lead_id}/notes",
        body=[{"note_type": "common", "params": {"text": f"{prefix}: created by amoCRM MCP smoke test"}}],
    )
    REPORT["created"]["note_id"] = first_id(note, "notes")
    call("notes.leads.list", "GET", f"/api/v4/leads/{lead_id}/notes", {"limit": 10})

    task = call(
        "tasks.create",
        "POST",
        "/api/v4/tasks",
        body=[
            {
                "text": f"{prefix}: follow up",
                "complete_till": int(time.time()) + 86400,
                "entity_id": lead_id,
                "entity_type": "leads",
            }
        ],
    )
    REPORT["created"]["task_id"] = first_id(task, "tasks")
    call("tasks.list", "GET", "/api/v4/tasks", {"filter[entity_id]": lead_id, "filter[entity_type]": "leads"})

    call(
        "links.contacts.link_company",
        "POST",
        f"/api/v4/contacts/{contact_id}/link",
        body=[{"to_entity_id": company_id, "to_entity_type": "companies"}],
    )

    catalog = call(
        "catalogs.create",
        "POST",
        "/api/v4/catalogs",
        body=[
            {
                "name": f"{prefix} Catalog",
                "type": "regular",
                "can_add_elements": True,
                "can_link_multiple": True,
                "request_id": "catalog",
            }
        ],
    )
    catalog_id = first_id(catalog, "catalogs")
    REPORT["created"]["catalog_id"] = catalog_id

    element = call(
        "catalog_elements.create",
        "POST",
        f"/api/v4/catalogs/{catalog_id}/elements",
        body=[{"name": f"{prefix} Catalog Element", "request_id": "element"}],
    )
    REPORT["created"]["catalog_element_id"] = first_id(element, "elements")
    call("catalog_elements.list", "GET", f"/api/v4/catalogs/{catalog_id}/elements", {"limit": 10})

    call("events.list", "GET", "/api/v4/events", {"limit": 10})
    call("webhooks.list", "GET", "/api/v4/webhooks")
    call("sources.list", "GET", "/api/v4/sources", {"limit": 10})
    call("leads.list", "GET", "/api/v4/leads", {"limit": 10, "query": prefix})

    REPORT["ok"] = True
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {REPORT_PATH}")
    print(json.dumps({"ok": True, "created": REPORT["created"], "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
    return 0


REPORT: dict[str, Any] = {"ok": False, "steps": {}, "created": {}}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StepFailed as exc:
        REPORT["failed_step"] = exc.label
        REPORT["failure"] = summarize_response(exc.response)
        REPORT_PATH.parent.mkdir(exist_ok=True)
        REPORT_PATH.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "failed_step": exc.label, "report": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
        raise
