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


REPORT_PATH = Path("test_reports/marketing_agency_setup.json")


def load_codex_amocrm_env() -> None:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    env = config.get("mcp_servers", {}).get("amocrm", {}).get("env", {})
    if isinstance(env, dict):
        for key, value in env.items():
            os.environ.setdefault(key, str(value))


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def fail(label: str, response: dict[str, Any]) -> None:
    REPORT["failed_step"] = label
    REPORT["failure"] = summarize(response)
    save_report(REPORT)
    raise RuntimeError(f"{label} failed with HTTP {response.get('status')}: {response.get('data')}")


def call(label: str, method: str, path: str, params: dict[str, Any] | None = None, body: Any | None = None) -> dict[str, Any]:
    response = server.amocrm_request(method, path, params=params, body=body)
    REPORT["steps"][label] = summarize(response)
    print(f"{label}: HTTP {response.get('status')} ok={response.get('ok')}")
    if not response.get("ok"):
        fail(label, response)
    return response


def summarize(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    result: dict[str, Any] = {
        "ok": response.get("ok"),
        "status": response.get("status"),
        "path": response.get("url", "").split(".amocrm.ru", 1)[-1],
    }
    if isinstance(data, dict):
        if "id" in data:
            result["id"] = data["id"]
        if "name" in data:
            result["name"] = data["name"]
        if "_embedded" in data and isinstance(data["_embedded"], dict):
            result["embedded_counts"] = {
                key: len(value) for key, value in data["_embedded"].items() if isinstance(value, list)
            }
        if "title" in data or "detail" in data:
            result["problem"] = {key: data.get(key) for key in ("title", "detail", "type") if key in data}
    return result


def embedded(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    value = data.get("_embedded", {}).get(key, [])
    return value if isinstance(value, list) else []


def list_collection(label: str, path: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    response = call(label, "GET", path, params=params or {"limit": 250})
    return embedded(response, key)


def first_created(response: dict[str, Any], key: str) -> dict[str, Any]:
    items = embedded(response, key)
    if not items:
        raise RuntimeError(f"No {key} in response")
    return items[0]


def enums(values: list[str]) -> list[dict[str, Any]]:
    return [{"value": value, "sort": index * 10} for index, value in enumerate(values, 1)]


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("name") == name), None)


def ensure_pipeline(name: str, sort: int, statuses: list[dict[str, Any]]) -> dict[str, Any]:
    pipelines = list_collection(f"pipelines.list.before.{name}", "/api/v4/leads/pipelines", "pipelines")
    existing = find_by_name(pipelines, name)
    if existing:
        pipeline = existing
        action = "existing"
    else:
        response = call(
            f"pipelines.create.{name}",
            "POST",
            "/api/v4/leads/pipelines",
            body=[
                {
                    "name": name,
                    "is_main": False,
                    "is_unsorted_on": True,
                    "sort": sort,
                    "_embedded": {"statuses": statuses},
                }
            ],
        )
        pipeline = first_created(response, "pipelines")
        action = "created"

    pipeline_id = int(pipeline["id"])
    current_statuses = list_collection(
        f"pipelines.statuses.list.{name}",
        f"/api/v4/leads/pipelines/{pipeline_id}/statuses",
        "statuses",
    )
    current_names = {item.get("name") for item in current_statuses}
    missing = [status for status in statuses if status["name"] not in current_names]
    if missing:
        call(
            f"pipelines.statuses.create_missing.{name}",
            "POST",
            f"/api/v4/leads/pipelines/{pipeline_id}/statuses",
            body=missing,
        )
        current_statuses = list_collection(
            f"pipelines.statuses.list.after.{name}",
            f"/api/v4/leads/pipelines/{pipeline_id}/statuses",
            "statuses",
        )

    REPORT["pipelines"][name] = {
        "action": action,
        "id": pipeline_id,
        "statuses": {item["name"]: item["id"] for item in current_statuses if item.get("name") and item.get("id")},
    }
    return REPORT["pipelines"][name]


def ensure_group(entity: str, name: str, sort: int) -> str | None:
    groups = list_collection(
        f"groups.list.{entity}.{name}",
        f"/api/v4/{entity}/custom_fields/groups",
        "custom_field_groups",
    )
    existing = find_by_name(groups, name)
    if existing:
        return existing.get("id")
    response = call(
        f"groups.create.{entity}.{name}",
        "POST",
        f"/api/v4/{entity}/custom_fields/groups",
        body=[{"name": name, "sort": sort}],
    )
    return first_created(response, "custom_field_groups").get("id")


def ensure_field(entity: str, spec: dict[str, Any]) -> dict[str, Any]:
    path = f"/api/v4/{entity}/custom_fields"
    fields = list_collection(f"fields.list.{entity}.{spec['name']}", path, "custom_fields")
    existing = find_by_name(fields, spec["name"])
    if existing:
        action = "existing"
        field = existing
    else:
        body = dict(spec)
        response = call(f"fields.create.{entity}.{spec['name']}", "POST", path, body=[body])
        field = first_created(response, "custom_fields")
        action = "created"
    REPORT["fields"].setdefault(entity, {})[spec["name"]] = {
        "action": action,
        "id": field.get("id"),
        "type": field.get("type"),
        "enums": [item.get("value") for item in field.get("enums") or []],
    }
    return field


def ensure_catalog(name: str) -> dict[str, Any]:
    catalogs = list_collection("catalogs.list.before", "/api/v4/catalogs", "catalogs")
    existing = find_by_name(catalogs, name)
    if existing:
        action = "existing"
        catalog = existing
    else:
        response = call(
            "catalogs.create.services",
            "POST",
            "/api/v4/catalogs",
            body=[
                {
                    "name": name,
                    "type": "regular",
                    "sort": 10,
                    "can_add_elements": True,
                    "can_link_multiple": True,
                }
            ],
        )
        catalog = first_created(response, "catalogs")
        action = "created"
    REPORT["catalog"] = {"action": action, "id": catalog["id"], "name": catalog["name"]}
    return catalog


def ensure_catalog_field(catalog_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    path = f"/api/v4/catalogs/{catalog_id}/custom_fields"
    fields = list_collection(f"catalog_fields.list.{spec['name']}", path, "custom_fields")
    existing = find_by_name(fields, spec["name"])
    if existing:
        action = "existing"
        field = existing
    else:
        response = call(f"catalog_fields.create.{spec['name']}", "POST", path, body=[dict(spec)])
        field = first_created(response, "custom_fields")
        action = "created"
    REPORT["catalog_fields"][spec["name"]] = {"action": action, "id": field.get("id"), "type": field.get("type")}
    return field


def ensure_catalog_element(catalog_id: int, name: str, values: list[dict[str, Any]]) -> dict[str, Any]:
    elements = list_collection(
        f"catalog_elements.list.{name}",
        f"/api/v4/catalogs/{catalog_id}/elements",
        "elements",
        {"limit": 250, "query": name},
    )
    existing = find_by_name(elements, name)
    if existing:
        action = "existing"
        element = existing
    else:
        response = call(
            f"catalog_elements.create.{name}",
            "POST",
            f"/api/v4/catalogs/{catalog_id}/elements",
            body=[{"name": name, "custom_fields_values": values}],
        )
        element = first_created(response, "elements")
        action = "created"
    REPORT["catalog_elements"][name] = {"action": action, "id": element.get("id")}
    return element


def ensure_tag(entity: str, name: str) -> str:
    items = list_collection(f"tags.list.{entity}.{name}", f"/api/v4/{entity}/tags", "tags", {"limit": 250, "query": name})
    existing = find_by_name(items, name)
    if existing:
        action = "existing"
        tag = existing
    else:
        response = call(f"tags.create.{entity}.{name}", "POST", f"/api/v4/{entity}/tags", body=[{"name": name}])
        tag = first_created(response, "tags")
        action = "created"
    REPORT["tags"].setdefault(entity, {})[name] = {"action": action, "id": tag.get("id")}
    return name


def ensure_entity(collection: str, name: str, payload: dict[str, Any], with_params: str | None = None) -> dict[str, Any]:
    params = {"limit": 50, "query": name}
    if with_params:
        params["with"] = with_params
    items = list_collection(f"{collection}.list.{name}", f"/api/v4/{collection}", collection, params)
    existing = find_by_name(items, name)
    if existing:
        action = "existing"
        entity = existing
    else:
        response = call(f"{collection}.create.{name}", "POST", f"/api/v4/{collection}", body=[payload])
        entity = first_created(response, collection)
        action = "created"
    REPORT["entities"].setdefault(collection, {})[name] = {"action": action, "id": entity.get("id")}
    return entity


def field_value(field: dict[str, Any], value: Any, enum_value: str | None = None) -> dict[str, Any]:
    if enum_value:
        enum_id = next((item.get("id") for item in field.get("enums") or [] if item.get("value") == enum_value), None)
        if enum_id:
            return {"field_id": field["id"], "values": [{"value": enum_value, "enum_id": enum_id}]}
    return {"field_id": field["id"], "values": [{"value": value}]}


def multiselect_value(field: dict[str, Any], values: list[str]) -> dict[str, Any]:
    available = {item.get("value"): item.get("id") for item in field.get("enums") or []}
    result = []
    for value in values:
        item: dict[str, Any] = {"value": value}
        if available.get(value):
            item["enum_id"] = available[value]
        result.append(item)
    return {"field_id": field["id"], "values": result}


def main() -> int:
    load_codex_amocrm_env()
    account = call("account.get", "GET", "/api/v4/account", {"with": "users_groups,task_types,version"})
    REPORT["account"] = {
        "id": account["data"].get("id"),
        "name": account["data"].get("name"),
        "subdomain": account["data"].get("subdomain"),
    }

    sales = ensure_pipeline(
        "Новые клиенты | Маркетинговое агентство",
        100,
        [
            {"name": "Получена новая заявка", "sort": 10, "color": "#fffeb2"},
            {"name": "Проведена квалификация", "sort": 20, "color": "#ffdc7f"},
            {"name": "Получен бриф", "sort": 30, "color": "#ffce5a"},
            {"name": "Сформирована стратегия и смета", "sort": 40, "color": "#d6eaff"},
            {"name": "Презентовано КП", "sort": 50, "color": "#c1e0ff"},
            {"name": "Согласованы условия", "sort": 60, "color": "#98cbff"},
            {"name": "Выставлен договор и счет", "sort": 70, "color": "#deff81"},
        ],
    )
    projects = ensure_pipeline(
        "Проекты и ретейнеры | Маркетинговое агентство",
        110,
        [
            {"name": "Проведен онбординг", "sort": 10, "color": "#fffeb2"},
            {"name": "Проведен аудит и согласована стратегия", "sort": 20, "color": "#ffdc7f"},
            {"name": "Подготовлен запуск", "sort": 30, "color": "#d6eaff"},
            {"name": "Запущены работы", "sort": 40, "color": "#c1e0ff"},
            {"name": "Отправлен отчет", "sort": 50, "color": "#f3beff"},
            {"name": "Согласовано продление или апсейл", "sort": 60, "color": "#deff81"},
        ],
    )

    lead_group_brief = ensure_group("leads", "Бриф и квалификация", 10)
    lead_group_money = ensure_group("leads", "Экономика и договор", 20)
    contact_group = ensure_group("contacts", "Роль и коммуникации", 10)
    company_group = ensure_group("companies", "Профиль клиента", 10)

    lead_specs = [
        {
            "name": "Услуги интереса",
            "type": "multiselect",
            "sort": 110,
            "group_id": lead_group_brief,
            "enums": enums(["SEO", "Контекстная реклама", "Таргетированная реклама", "SMM", "Контент-маркетинг", "Брендинг", "Сайт/лендинг", "Аналитика", "CRM-маркетинг"]),
        },
        {
            "name": "Цель кампании",
            "type": "select",
            "sort": 120,
            "group_id": lead_group_brief,
            "enums": enums(["Лиды", "Продажи", "Узнаваемость", "Запуск продукта", "Повторные продажи", "Найм/HR-маркетинг"]),
        },
        {"name": "URL сайта", "type": "url", "sort": 130, "group_id": lead_group_brief},
        {"name": "KPI / целевой результат", "type": "textarea", "sort": 140, "group_id": lead_group_brief},
        {
            "name": "Приоритет лида",
            "type": "select",
            "sort": 150,
            "group_id": lead_group_brief,
            "enums": enums(["A: горячий", "B: теплый", "C: nurture"]),
        },
        {
            "name": "Источник заявки",
            "type": "select",
            "sort": 160,
            "group_id": lead_group_brief,
            "enums": enums(["Сайт", "Рекомендация", "Контекст", "Соцсети", "Партнер", "Ивент", "Холодный outreach"]),
        },
        {"name": "Месячный бюджет, ₽", "type": "numeric", "sort": 210, "group_id": lead_group_money},
        {"name": "Дата старта проекта", "type": "date", "sort": 220, "group_id": lead_group_money},
        {"name": "Срок договора, мес.", "type": "numeric", "sort": 230, "group_id": lead_group_money},
        {
            "name": "Вероятность продления",
            "type": "select",
            "sort": 240,
            "group_id": lead_group_money,
            "enums": enums(["Высокая", "Средняя", "Низкая", "Не оценено"]),
        },
    ]
    lead_fields = {spec["name"]: ensure_field("leads", {k: v for k, v in spec.items() if v is not None}) for spec in lead_specs}

    contact_specs = [
        {
            "name": "Роль в сделке",
            "type": "select",
            "sort": 110,
            "group_id": contact_group,
            "enums": enums(["Владелец", "CEO", "CMO/маркетолог", "Руководитель продаж", "Финансы/закупки", "Операционный контакт"]),
        },
        {
            "name": "Предпочтительный канал",
            "type": "select",
            "sort": 120,
            "group_id": contact_group,
            "enums": enums(["Телефон", "Telegram", "WhatsApp", "Email", "Zoom/Meet"]),
        },
        {"name": "Telegram", "type": "text", "sort": 130, "group_id": contact_group},
        {"name": "LinkedIn / соцсеть", "type": "url", "sort": 140, "group_id": contact_group},
    ]
    contact_fields = {spec["name"]: ensure_field("contacts", {k: v for k, v in spec.items() if v is not None}) for spec in contact_specs}

    company_specs = [
        {
            "name": "Отрасль клиента",
            "type": "select",
            "sort": 110,
            "group_id": company_group,
            "enums": enums(["E-commerce", "SaaS/IT", "Недвижимость", "Медицина", "Образование", "Финансы", "HoReCa", "B2B услуги", "Производство"]),
        },
        {
            "name": "Размер бизнеса",
            "type": "select",
            "sort": 120,
            "group_id": company_group,
            "enums": enums(["Стартап", "Малый бизнес", "Средний бизнес", "Enterprise"]),
        },
        {"name": "Средний чек клиента, ₽", "type": "numeric", "sort": 130, "group_id": company_group},
        {"name": "География", "type": "text", "sort": 140, "group_id": company_group},
        {"name": "Текущий стек маркетинга", "type": "textarea", "sort": 150, "group_id": company_group},
    ]
    company_fields = {spec["name"]: ensure_field("companies", {k: v for k, v in spec.items() if v is not None}) for spec in company_specs}

    catalog = ensure_catalog("Услуги агентства")
    catalog_id = int(catalog["id"])
    catalog_fields = {
        "Тип услуги": ensure_catalog_field(
            catalog_id,
            {"name": "Тип услуги", "type": "select", "sort": 10, "is_visible": True, "enums": enums(["Разовая услуга", "Ретейнер", "Проект", "Аудит"])},
        ),
        "Стоимость в месяц, ₽": ensure_catalog_field(catalog_id, {"name": "Стоимость в месяц, ₽", "type": "numeric", "sort": 20, "is_visible": True}),
        "Минимальный срок, мес.": ensure_catalog_field(catalog_id, {"name": "Минимальный срок, мес.", "type": "numeric", "sort": 30, "is_visible": True}),
        "Описание результата": ensure_catalog_field(catalog_id, {"name": "Описание результата", "type": "textarea", "sort": 40, "is_visible": True}),
    }

    for service in [
        ("SEO Retainer", "Ретейнер", 180000, 6, "Рост органического трафика, техаудит, контент-план, ежемесячная отчетность"),
        ("Performance Ads", "Ретейнер", 220000, 3, "Контекст и таргет, медиаплан, запуск, оптимизация CPA/ROAS"),
        ("SMM + Content", "Ретейнер", 150000, 3, "Контент-стратегия, рубрикатор, публикации, комьюнити-менеджмент"),
        ("Brand Sprint", "Проект", 450000, 1, "Позиционирование, айдентика, бренд-гайд и коммуникационная платформа"),
        ("Marketing Audit", "Аудит", 120000, 1, "Аудит каналов, аналитики, сайта и воронки с дорожной картой роста"),
    ]:
        name, service_type, price, months, description = service
        ensure_catalog_element(
            catalog_id,
            name,
            [
                field_value(catalog_fields["Тип услуги"], service_type, service_type),
                field_value(catalog_fields["Стоимость в месяц, ₽"], price),
                field_value(catalog_fields["Минимальный срок, мес."], months),
                field_value(catalog_fields["Описание результата"], description),
            ],
        )

    for tag_name in ["Входящий лид", "Ретейнер", "Performance", "SEO", "SMM", "Высокий бюджет", "Нужен бриф", "Кейс/портфолио отправлено"]:
        ensure_tag("leads", tag_name)

    company = ensure_entity(
        "companies",
        "Demo Client | Urban Coffee",
        {
            "name": "Demo Client | Urban Coffee",
            "custom_fields_values": [
                field_value(company_fields["Отрасль клиента"], "HoReCa", "HoReCa"),
                field_value(company_fields["Размер бизнеса"], "Средний бизнес", "Средний бизнес"),
                field_value(company_fields["Средний чек клиента, ₽"], 850),
                field_value(company_fields["География"], "Москва, Санкт-Петербург"),
                field_value(company_fields["Текущий стек маркетинга"], "VK Ads, Яндекс Директ, Roistat, Tilda"),
            ],
        },
        "contacts,leads",
    )
    contact = ensure_entity(
        "contacts",
        "Анна Маркетингова | Urban Coffee",
        {
            "name": "Анна Маркетингова | Urban Coffee",
            "custom_fields_values": [
                {"field_code": "PHONE", "values": [{"value": "+79990001122", "enum_code": "WORK"}]},
                {"field_code": "EMAIL", "values": [{"value": "marketing@example.test", "enum_code": "WORK"}]},
                field_value(contact_fields["Роль в сделке"], "CMO/маркетолог", "CMO/маркетолог"),
                field_value(contact_fields["Предпочтительный канал"], "Telegram", "Telegram"),
                field_value(contact_fields["Telegram"], "@urban_cmo"),
            ],
            "_embedded": {"companies": [{"id": company["id"]}]},
        },
        "leads",
    )

    lead = ensure_entity(
        "leads",
        "Urban Coffee | Performance + SMM",
        {
            "name": "Urban Coffee | Performance + SMM",
            "price": 420000,
            "pipeline_id": sales["id"],
            "status_id": sales["statuses"].get("Получен бриф"),
            "custom_fields_values": [
                multiselect_value(lead_fields["Услуги интереса"], ["Контекстная реклама", "Таргетированная реклама", "SMM"]),
                field_value(lead_fields["Цель кампании"], "Лиды", "Лиды"),
                field_value(lead_fields["URL сайта"], "https://example.test"),
                field_value(lead_fields["KPI / целевой результат"], "120 заявок в месяц, CPL до 1500 ₽, рост повторных заказов"),
                field_value(lead_fields["Приоритет лида"], "A: горячий", "A: горячий"),
                field_value(lead_fields["Источник заявки"], "Рекомендация", "Рекомендация"),
                field_value(lead_fields["Месячный бюджет, ₽"], 420000),
                field_value(lead_fields["Дата старта проекта"], int(time.time()) + 14 * 86400),
                field_value(lead_fields["Срок договора, мес."], 6),
                field_value(lead_fields["Вероятность продления"], "Высокая", "Высокая"),
            ],
            "_embedded": {
                "contacts": [{"id": contact["id"]}],
                "companies": [{"id": company["id"]}],
                "tags": [{"name": "Входящий лид"}, {"name": "Performance"}, {"name": "SMM"}, {"name": "Высокий бюджет"}],
            },
        },
        "contacts,companies",
    )

    call(
        "notes.lead.add.brief",
        "POST",
        f"/api/v4/leads/{lead['id']}/notes",
        body=[
            {
                "note_type": "common",
                "params": {
                    "text": "Стартовая карточка для маркетингового агентства: клиент хочет performance + SMM, бюджет 420 000 ₽/мес, решение принимает CMO."
                },
            }
        ],
    )
    call(
        "tasks.lead.add.next_step",
        "POST",
        "/api/v4/tasks",
        body=[
            {
                "text": "Подготовить медиаплан и список вопросов к брифу",
                "complete_till": int(time.time()) + 2 * 86400,
                "entity_id": lead["id"],
                "entity_type": "leads",
            }
        ],
    )

    call("verify.pipelines", "GET", "/api/v4/leads/pipelines")
    call("verify.lead_fields", "GET", "/api/v4/leads/custom_fields", {"limit": 250})
    call("verify.catalog_elements", "GET", f"/api/v4/catalogs/{catalog_id}/elements", {"limit": 250})
    call("verify.demo_lead", "GET", f"/api/v4/leads/{lead['id']}", {"with": "contacts,companies"})

    REPORT["ok"] = True
    save_report(REPORT)
    print(json.dumps({"ok": True, "report": str(REPORT_PATH), "summary": summary_for_print()}, ensure_ascii=False, indent=2))
    return 0


def summary_for_print() -> dict[str, Any]:
    return {
        "account": REPORT.get("account"),
        "pipelines": REPORT.get("pipelines"),
        "catalog": REPORT.get("catalog"),
        "catalog_elements": REPORT.get("catalog_elements"),
        "demo_entities": REPORT.get("entities"),
    }


REPORT: dict[str, Any] = {
    "ok": False,
    "steps": {},
    "pipelines": {},
    "fields": {},
    "catalog_fields": {},
    "catalog_elements": {},
    "tags": {},
    "entities": {},
}


if __name__ == "__main__":
    raise SystemExit(main())
