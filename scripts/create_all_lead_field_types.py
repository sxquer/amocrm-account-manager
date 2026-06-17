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


REPORT_PATH = Path("test_reports/lead_field_types.json")


def load_codex_env() -> None:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    env = config.get("mcp_servers", {}).get("amocrm", {}).get("env", {})
    if isinstance(env, dict):
        for key, value in env.items():
            os.environ.setdefault(key, str(value))


def save_report() -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")


def embedded(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    value = data.get("_embedded", {}).get(key, [])
    return value if isinstance(value, list) else []


def summarize_error(response: dict[str, Any]) -> Any:
    data = response.get("data")
    if isinstance(data, dict):
        return {key: data.get(key) for key in ("title", "detail", "status", "validation-errors") if key in data}
    return data


def call(method: str, path: str, params: dict[str, Any] | None = None, body: Any | None = None) -> dict[str, Any]:
    return server.amocrm_request(method, path, params=params, body=body)


def create_group(name: str) -> str:
    response = call("POST", "/api/v4/leads/custom_fields/groups", body=[{"name": name, "sort": 900}])
    if not response.get("ok"):
        raise RuntimeError(f"Cannot create field group: {response.get('data')}")
    return embedded(response, "custom_field_groups")[0]["id"]


def create_catalog(name: str) -> int | None:
    response = call(
        "POST",
        "/api/v4/catalogs",
        body=[
            {
                "name": name,
                "type": "regular",
                "can_add_elements": True,
                "can_link_multiple": True,
            }
        ],
    )
    if not response.get("ok"):
        REPORT["support"]["catalog_errors"].append({"name": name, "status": response.get("status"), "error": summarize_error(response)})
        return None
    return int(embedded(response, "catalogs")[0]["id"])


def enum_values(*values: str) -> list[dict[str, Any]]:
    return [{"value": value, "sort": index * 10} for index, value in enumerate(values, 1)]


def create_field(spec: dict[str, Any]) -> None:
    field_type = spec["type"]
    name = spec["name"]
    try:
        response = call("POST", "/api/v4/leads/custom_fields", body=[spec])
    except Exception as exc:  # noqa: BLE001 - keep the broad type sweep running.
        REPORT["failed"].append(
            {
                "type": field_type,
                "name": name,
                "status": "exception",
                "error": str(exc),
                "request": spec,
            }
        )
        save_report()
        print(f"failed {field_type}: exception {name}: {exc}")
        return

    if response.get("ok"):
        field = embedded(response, "custom_fields")[0]
        REPORT["created"].append(
            {
                "type": field_type,
                "name": name,
                "id": field.get("id"),
                "group_id": field.get("group_id"),
                "enums": field.get("enums"),
                "currency": field.get("currency"),
            }
        )
        print(f"created {field_type}: {field.get('id')} {name}")
    else:
        REPORT["failed"].append(
            {
                "type": field_type,
                "name": name,
                "status": response.get("status"),
                "error": summarize_error(response),
                "request": spec,
            }
        )
        print(f"failed {field_type}: HTTP {response.get('status')} {name}")
    save_report()


def main() -> int:
    load_codex_env()
    missing = [key for key in ("AMOCRM_BASE_URL", "AMOCRM_LONG_LIVED_TOKEN") if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")

    suffix = time.strftime("%Y%m%d-%H%M%S")
    prefix = f"MCP Field Types {suffix}"
    REPORT["prefix"] = prefix

    account = call("GET", "/api/v4/account")
    if not account.get("ok"):
        raise RuntimeError(f"Cannot access account: {account.get('data')}")
    REPORT["account"] = {
        "id": account["data"].get("id"),
        "name": account["data"].get("name"),
        "subdomain": account["data"].get("subdomain"),
    }

    group_id = create_group(prefix)
    REPORT["group"] = {"id": group_id, "name": prefix}

    parent_catalog_id = create_catalog(f"{prefix} Parent Catalog")
    child_catalog_id = create_catalog(f"{prefix} Child Catalog")
    REPORT["support"]["parent_catalog_id"] = parent_catalog_id
    REPORT["support"]["child_catalog_id"] = child_catalog_id

    base_specs: list[dict[str, Any]] = [
        {"type": "text", "name": f"{prefix} / text"},
        {"type": "numeric", "name": f"{prefix} / numeric"},
        {"type": "checkbox", "name": f"{prefix} / checkbox"},
        {"type": "select", "name": f"{prefix} / select", "enums": enum_values("Вариант A", "Вариант B")},
        {"type": "multiselect", "name": f"{prefix} / multiselect", "enums": enum_values("SEO", "PPC", "SMM")},
        {"type": "date", "name": f"{prefix} / date"},
        {"type": "url", "name": f"{prefix} / url"},
        {"type": "date_time", "name": f"{prefix} / date_time"},
        {"type": "textarea", "name": f"{prefix} / textarea"},
        {"type": "radiobutton", "name": f"{prefix} / radiobutton", "enums": enum_values("Да", "Нет")},
        {"type": "streetaddress", "name": f"{prefix} / streetaddress"},
        {"type": "smart_address", "name": f"{prefix} / smart_address"},
        {"type": "birthday", "name": f"{prefix} / birthday", "remind": "never"},
        {"type": "legal_entity", "name": f"{prefix} / legal_entity"},
        {
            "type": "tracking_data",
            "name": f"{prefix} / tracking_data",
            "tracking_callback": "amocrmMcpTrackingCallback",
        },
        {"type": "monetary", "name": f"{prefix} / monetary", "currency": "RUB"},
        {"type": "file", "name": f"{prefix} / file"},
    ]

    if parent_catalog_id and child_catalog_id:
        base_specs.append(
            {
                "type": "chained_list",
                "name": f"{prefix} / chained_list",
                "chained_lists": [
                    {"title": "Родитель", "catalog_id": parent_catalog_id},
                    {"title": "Дочерний", "catalog_id": child_catalog_id, "parent_catalog_id": parent_catalog_id},
                ],
            }
        )

    for index, spec in enumerate(base_specs, 1):
        spec = dict(spec)
        spec["sort"] = 900 + index
        spec["group_id"] = group_id
        create_field(spec)

    verify = call("GET", "/api/v4/leads/custom_fields", params={"limit": 250})
    if verify.get("ok"):
        created_ids = {item["id"] for item in REPORT["created"]}
        fields = [field for field in embedded(verify, "custom_fields") if field.get("id") in created_ids]
        REPORT["verified"] = [
            {
                "id": field.get("id"),
                "name": field.get("name"),
                "type": field.get("type"),
                "group_id": field.get("group_id"),
            }
            for field in fields
        ]
    else:
        REPORT["verify_error"] = summarize_error(verify)

    REPORT["ok"] = len(REPORT["created"]) > 0
    save_report()
    print(
        json.dumps(
            {
                "ok": REPORT["ok"],
                "created_count": len(REPORT["created"]),
                "failed_count": len(REPORT["failed"]),
                "group": REPORT["group"],
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


REPORT: dict[str, Any] = {
    "ok": False,
    "created": [],
    "failed": [],
    "support": {"catalog_errors": []},
}


if __name__ == "__main__":
    raise SystemExit(main())
