from __future__ import annotations

import json
import os
import tempfile
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback.
    fcntl = None  # type: ignore[assignment]


API_VERSION = "2024-11-05"
SERVER_NAME = "amocrm-mcp"
TOKEN_ENV_NAMES = ("AMOCRM_LONG_LIVED_TOKEN", "AMOCRM_ACCESS_TOKEN", "AMOCRM_TOKEN")
ENTITY_COLLECTIONS = (
    "leads",
    "contacts",
    "companies",
    "customers",
    "tasks",
    "catalogs",
    "users",
    "roles",
    "events",
    "webhooks",
    "widgets",
    "sources",
    "chat_templates",
    "conversations",
)
CUSTOM_FIELD_ENTITIES = ("leads", "contacts", "companies", "customers", "catalogs")
TAG_ENTITIES = ("leads", "contacts", "companies", "customers")
NOTE_ENTITIES = ("leads", "contacts", "companies", "customers")
LINK_ENTITIES = ("leads", "contacts", "companies", "customers")
HTTP_METHODS = ("GET", "POST", "PATCH", "DELETE")
DEFAULT_RATE_LIMIT_SECONDS = 1.0
_PROCESS_RATE_LIMIT_LOCK = threading.Lock()
_PROCESS_LAST_REQUEST_AT = 0.0
READ_METHODS = ("GET",)
WRITE_METHODS = ("POST", "PATCH", "DELETE")
LOCAL_ENV_FILENAMES = (".env", ".amocrm.env")
_LOCAL_ENV_LOCK = threading.Lock()
_LOCAL_ENV_LOADED = False
_LOCAL_ENV_SOURCE: str | None = None
_LOCAL_ENV_KEYS: set[str] = set()


RESOURCE_ACTIONS: dict[str, dict[str, dict[str, str]]] = {
    "account": {
        "get": {"method": "GET", "path": "/api/v4/account"},
    },
    "leads": {
        "list": {"method": "GET", "path": "/api/v4/leads"},
        "get": {"method": "GET", "path": "/api/v4/leads/{id}"},
        "create": {"method": "POST", "path": "/api/v4/leads"},
        "complex_create": {"method": "POST", "path": "/api/v4/leads/complex"},
        "update": {"method": "PATCH", "path": "/api/v4/leads"},
        "update_one": {"method": "PATCH", "path": "/api/v4/leads/{id}"},
    },
    "contacts": {
        "list": {"method": "GET", "path": "/api/v4/contacts"},
        "get": {"method": "GET", "path": "/api/v4/contacts/{id}"},
        "create": {"method": "POST", "path": "/api/v4/contacts"},
        "complex_create": {"method": "POST", "path": "/api/v4/contacts/complex"},
        "update": {"method": "PATCH", "path": "/api/v4/contacts"},
        "update_one": {"method": "PATCH", "path": "/api/v4/contacts/{id}"},
    },
    "companies": {
        "list": {"method": "GET", "path": "/api/v4/companies"},
        "get": {"method": "GET", "path": "/api/v4/companies/{id}"},
        "create": {"method": "POST", "path": "/api/v4/companies"},
        "update": {"method": "PATCH", "path": "/api/v4/companies"},
        "update_one": {"method": "PATCH", "path": "/api/v4/companies/{id}"},
    },
    "customers": {
        "list": {"method": "GET", "path": "/api/v4/customers"},
        "get": {"method": "GET", "path": "/api/v4/customers/{id}"},
        "create": {"method": "POST", "path": "/api/v4/customers"},
        "update": {"method": "PATCH", "path": "/api/v4/customers"},
        "update_one": {"method": "PATCH", "path": "/api/v4/customers/{id}"},
    },
    "tasks": {
        "list": {"method": "GET", "path": "/api/v4/tasks"},
        "get": {"method": "GET", "path": "/api/v4/tasks/{id}"},
        "create": {"method": "POST", "path": "/api/v4/tasks"},
        "update": {"method": "PATCH", "path": "/api/v4/tasks"},
        "update_one": {"method": "PATCH", "path": "/api/v4/tasks/{id}"},
    },
    "pipelines": {
        "list": {"method": "GET", "path": "/api/v4/leads/pipelines"},
        "get": {"method": "GET", "path": "/api/v4/leads/pipelines/{pipeline_id}"},
        "create": {"method": "POST", "path": "/api/v4/leads/pipelines"},
        "update": {"method": "PATCH", "path": "/api/v4/leads/pipelines"},
        "update_one": {"method": "PATCH", "path": "/api/v4/leads/pipelines/{pipeline_id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/leads/pipelines/{pipeline_id}"},
    },
    "pipeline_statuses": {
        "list": {"method": "GET", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses"},
        "get": {"method": "GET", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses/{status_id}"},
        "create": {"method": "POST", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses"},
        "update": {"method": "PATCH", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses"},
        "update_one": {"method": "PATCH", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses/{status_id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/leads/pipelines/{pipeline_id}/statuses/{status_id}"},
    },
    "loss_reasons": {
        "list": {"method": "GET", "path": "/api/v4/leads/loss_reasons"},
        "get": {"method": "GET", "path": "/api/v4/leads/loss_reasons/{id}"},
        "create": {"method": "POST", "path": "/api/v4/leads/loss_reasons"},
        "update": {"method": "PATCH", "path": "/api/v4/leads/loss_reasons"},
        "update_one": {"method": "PATCH", "path": "/api/v4/leads/loss_reasons/{id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/leads/loss_reasons/{id}"},
    },
    "custom_fields": {
        "list": {"method": "GET", "path": "/api/v4/{entity_type}/custom_fields"},
        "get": {"method": "GET", "path": "/api/v4/{entity_type}/custom_fields/{field_id}"},
        "create": {"method": "POST", "path": "/api/v4/{entity_type}/custom_fields"},
        "update": {"method": "PATCH", "path": "/api/v4/{entity_type}/custom_fields"},
        "update_one": {"method": "PATCH", "path": "/api/v4/{entity_type}/custom_fields/{field_id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/{entity_type}/custom_fields/{field_id}"},
    },
    "custom_field_groups": {
        "list": {"method": "GET", "path": "/api/v4/{entity_type}/custom_fields/groups"},
        "create": {"method": "POST", "path": "/api/v4/{entity_type}/custom_fields/groups"},
        "update": {"method": "PATCH", "path": "/api/v4/{entity_type}/custom_fields/groups"},
        "delete": {"method": "DELETE", "path": "/api/v4/{entity_type}/custom_fields/groups/{group_id}"},
    },
    "tags": {
        "list": {"method": "GET", "path": "/api/v4/{entity_type}/tags"},
        "create": {"method": "POST", "path": "/api/v4/{entity_type}/tags"},
    },
    "notes": {
        "list_all": {"method": "GET", "path": "/api/v4/{entity_type}/notes"},
        "create_many": {"method": "POST", "path": "/api/v4/{entity_type}/notes"},
        "update_many": {"method": "PATCH", "path": "/api/v4/{entity_type}/notes"},
        "list": {"method": "GET", "path": "/api/v4/{entity_type}/{entity_id}/notes"},
        "create": {"method": "POST", "path": "/api/v4/{entity_type}/{entity_id}/notes"},
        "update_one": {"method": "PATCH", "path": "/api/v4/{entity_type}/{entity_id}/notes/{note_id}"},
    },
    "links": {
        "link": {"method": "POST", "path": "/api/v4/{entity_type}/{entity_id}/link"},
        "unlink": {"method": "DELETE", "path": "/api/v4/{entity_type}/{entity_id}/link"},
    },
    "catalogs": {
        "list": {"method": "GET", "path": "/api/v4/catalogs"},
        "get": {"method": "GET", "path": "/api/v4/catalogs/{catalog_id}"},
        "create": {"method": "POST", "path": "/api/v4/catalogs"},
        "update": {"method": "PATCH", "path": "/api/v4/catalogs"},
        "update_one": {"method": "PATCH", "path": "/api/v4/catalogs/{catalog_id}"},
    },
    "catalog_elements": {
        "list": {"method": "GET", "path": "/api/v4/catalogs/{catalog_id}/elements"},
        "get": {"method": "GET", "path": "/api/v4/catalogs/{catalog_id}/elements/{element_id}"},
        "create": {"method": "POST", "path": "/api/v4/catalogs/{catalog_id}/elements"},
        "update": {"method": "PATCH", "path": "/api/v4/catalogs/{catalog_id}/elements"},
        "update_one": {"method": "PATCH", "path": "/api/v4/catalogs/{catalog_id}/elements/{element_id}"},
    },
    "customer_transactions": {
        "list": {"method": "GET", "path": "/api/v4/customers/{customer_id}/transactions"},
        "create": {"method": "POST", "path": "/api/v4/customers/{customer_id}/transactions"},
        "delete": {"method": "DELETE", "path": "/api/v4/customers/{customer_id}/transactions/{transaction_id}"},
    },
    "users": {
        "list": {"method": "GET", "path": "/api/v4/users"},
        "get": {"method": "GET", "path": "/api/v4/users/{id}"},
        "invite": {"method": "POST", "path": "/api/v4/users"},
    },
    "roles": {
        "list": {"method": "GET", "path": "/api/v4/roles"},
        "get": {"method": "GET", "path": "/api/v4/roles/{id}"},
        "create": {"method": "POST", "path": "/api/v4/roles"},
        "update": {"method": "PATCH", "path": "/api/v4/roles"},
        "delete": {"method": "DELETE", "path": "/api/v4/roles/{id}"},
    },
    "webhooks": {
        "list": {"method": "GET", "path": "/api/v4/webhooks"},
        "subscribe": {"method": "POST", "path": "/api/v4/webhooks"},
        "unsubscribe": {"method": "DELETE", "path": "/api/v4/webhooks"},
    },
    "sources": {
        "list": {"method": "GET", "path": "/api/v4/sources"},
        "get": {"method": "GET", "path": "/api/v4/sources/{id}"},
        "create": {"method": "POST", "path": "/api/v4/sources"},
        "update": {"method": "PATCH", "path": "/api/v4/sources"},
        "update_one": {"method": "PATCH", "path": "/api/v4/sources/{id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/sources/{id}"},
    },
    "unsorted": {
        "list": {"method": "GET", "path": "/api/v4/leads/unsorted"},
        "summary": {"method": "GET", "path": "/api/v4/leads/unsorted/summary"},
        "add_sip": {"method": "POST", "path": "/api/v4/leads/unsorted/sip"},
        "add_forms": {"method": "POST", "path": "/api/v4/leads/unsorted/forms"},
        "add_chats": {"method": "POST", "path": "/api/v4/leads/unsorted/chats"},
        "add_mail": {"method": "POST", "path": "/api/v4/leads/unsorted/mail"},
        "accept": {"method": "POST", "path": "/api/v4/leads/unsorted/{uid}/accept"},
        "decline": {"method": "DELETE", "path": "/api/v4/leads/unsorted/{uid}/decline"},
        "link": {"method": "POST", "path": "/api/v4/leads/unsorted/{uid}/link"},
    },
    "events": {
        "list": {"method": "GET", "path": "/api/v4/events"},
    },
    "widgets": {
        "list": {"method": "GET", "path": "/api/v4/widgets"},
        "install": {"method": "POST", "path": "/api/v4/widgets/{widget_code}"},
        "disable": {"method": "DELETE", "path": "/api/v4/widgets/{widget_code}"},
    },
    "conversations": {
        "list": {"method": "GET", "path": "/api/v4/conversations"},
        "get": {"method": "GET", "path": "/api/v4/conversations/{id}"},
        "close": {"method": "POST", "path": "/api/v4/conversations/{id}/close"},
    },
    "short_links": {
        "create": {"method": "POST", "path": "/api/v4/short_links"},
    },
    "calls": {
        "add": {"method": "POST", "path": "/api/v4/calls"},
    },
    "chat_templates": {
        "list": {"method": "GET", "path": "/api/v4/chat_templates"},
        "get": {"method": "GET", "path": "/api/v4/chat_templates/{id}"},
        "create": {"method": "POST", "path": "/api/v4/chat_templates"},
        "update": {"method": "PATCH", "path": "/api/v4/chat_templates/{id}"},
        "delete": {"method": "DELETE", "path": "/api/v4/chat_templates/{id}"},
    },
}


class McpError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class AmoConfig:
    base_url: str
    token: str
    timeout: float
    token_env: str


def reset_local_env_cache() -> None:
    global _LOCAL_ENV_LOADED, _LOCAL_ENV_SOURCE, _LOCAL_ENV_KEYS
    with _LOCAL_ENV_LOCK:
        _LOCAL_ENV_LOADED = False
        _LOCAL_ENV_SOURCE = None
        _LOCAL_ENV_KEYS = set()


def strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value.strip()


def parse_env_value(value: str) -> str:
    value = strip_inline_comment(value.strip())
    quote = value[0] if value else ""
    if len(value) >= 2 and value[0] == value[-1] and quote in {"'", '"'}:
        value = value[1:-1]
        if quote == '"':
            return bytes(value, "utf-8").decode("unicode_escape")
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if not key.startswith("AMOCRM_"):
            continue
        values[key] = parse_env_value(raw_value)
    return values


def find_local_env_file(start: Path | None = None) -> Path | None:
    explicit_path = os.environ.get("AMOCRM_ENV_FILE")
    if explicit_path:
        path = Path(explicit_path).expanduser()
        return path if path.is_file() else None

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        for filename in LOCAL_ENV_FILENAMES:
            path = directory / filename
            if path.is_file():
                return path
    return None


def load_local_env(force: bool = False) -> dict[str, Any]:
    global _LOCAL_ENV_LOADED, _LOCAL_ENV_SOURCE, _LOCAL_ENV_KEYS
    with _LOCAL_ENV_LOCK:
        if _LOCAL_ENV_LOADED and not force:
            return {
                "loaded": bool(_LOCAL_ENV_SOURCE),
                "source": _LOCAL_ENV_SOURCE,
                "keys": sorted(_LOCAL_ENV_KEYS),
            }

        path = find_local_env_file()
        _LOCAL_ENV_LOADED = True
        _LOCAL_ENV_SOURCE = str(path) if path else None
        _LOCAL_ENV_KEYS = set()
        if not path:
            return {"loaded": False, "source": None, "keys": []}

        values = parse_env_file(path)
        for key, value in values.items():
            os.environ[key] = value
        _LOCAL_ENV_KEYS = set(values.keys())
        return {
            "loaded": True,
            "source": _LOCAL_ENV_SOURCE,
            "keys": sorted(_LOCAL_ENV_KEYS),
        }


def first_env(names: tuple[str, ...]) -> tuple[str, str] | tuple[None, None]:
    load_local_env()
    for name in names:
        value = os.environ.get(name)
        if value:
            return name, value
    return None, None


def truthy_env(name: str) -> bool:
    load_local_env()
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def csv_env(*names: str) -> set[str]:
    load_local_env()
    values: set[str] = set()
    for name in names:
        raw_value = os.environ.get(name, "")
        for item in raw_value.split(","):
            normalized = item.strip().lower()
            if normalized:
                values.add(normalized)
    return values


def configured_base_url() -> str | None:
    load_local_env()
    base_url = os.environ.get("AMOCRM_BASE_URL")
    if base_url:
        return base_url.rstrip("/")

    subdomain = os.environ.get("AMOCRM_SUBDOMAIN")
    if not subdomain:
        return None

    suffix = os.environ.get("AMOCRM_DOMAIN_SUFFIX", "amocrm.ru").strip(".")
    return f"https://{subdomain}.{suffix}".rstrip("/")


def load_config() -> AmoConfig:
    base_url = configured_base_url()
    if not base_url:
        raise McpError(
            -32001,
            "amoCRM base URL is not configured. Set AMOCRM_BASE_URL or AMOCRM_SUBDOMAIN.",
        )

    token_env, token = first_env(TOKEN_ENV_NAMES)
    if not token:
        raise McpError(
            -32001,
            "amoCRM token is not configured. Set AMOCRM_LONG_LIVED_TOKEN.",
        )

    timeout = float(os.environ.get("AMOCRM_TIMEOUT", "30"))
    return AmoConfig(base_url=base_url, token=token, timeout=timeout, token_env=token_env or "")


def rate_limit_interval_seconds() -> float:
    load_local_env()
    raw_value = os.environ.get("AMOCRM_RATE_LIMIT_SECONDS", str(DEFAULT_RATE_LIMIT_SECONDS))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise McpError(-32001, "AMOCRM_RATE_LIMIT_SECONDS must be a number.") from exc
    if value < 0:
        raise McpError(-32001, "AMOCRM_RATE_LIMIT_SECONDS must be greater than or equal to 0.")
    return value


def rate_limit_lock_path() -> str:
    load_local_env()
    return os.environ.get(
        "AMOCRM_RATE_LIMIT_LOCK_FILE",
        os.path.join(tempfile.gettempdir(), "amocrm_mcp_rate_limit.lock"),
    )


def acquire_rate_limit_slot() -> None:
    interval = rate_limit_interval_seconds()
    if interval == 0:
        return

    if fcntl is None:
        acquire_process_rate_limit_slot(interval)
        return

    path = rate_limit_lock_path()
    lock_dir = os.path.dirname(path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            lock_file.seek(0)
            raw_last_request = lock_file.read().strip()
            try:
                last_request_at = float(raw_last_request) if raw_last_request else 0.0
            except ValueError:
                last_request_at = 0.0

            now = time.monotonic()
            wait_for = interval - (now - last_request_at)
            if wait_for > 0:
                time.sleep(wait_for)
                now = time.monotonic()

            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"{now:.9f}")
            lock_file.flush()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def acquire_process_rate_limit_slot(interval: float) -> None:
    global _PROCESS_LAST_REQUEST_AT
    with _PROCESS_RATE_LIMIT_LOCK:
        now = time.monotonic()
        wait_for = interval - (now - _PROCESS_LAST_REQUEST_AT)
        if wait_for > 0:
            time.sleep(wait_for)
            now = time.monotonic()
        _PROCESS_LAST_REQUEST_AT = now


def write_policy() -> dict[str, Any]:
    return {
        "readonly": truthy_env("AMOCRM_READONLY"),
        "write_allowlist": sorted(csv_env("AMOCRM_WRITE_ALLOWLIST", "AMOCRM_MUTATION_ALLOWLIST")),
        "write_denylist": sorted(csv_env("AMOCRM_WRITE_DENYLIST", "AMOCRM_MUTATION_DENYLIST")),
    }


def classify_api_resource(path_or_url: str) -> str:
    parsed = urllib.parse.urlparse(path_or_url)
    path = parsed.path or path_or_url
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3 or parts[0] != "api":
        return "unknown"

    resource = parts[2]
    if resource in {"leads", "contacts", "companies", "customers", "catalogs"}:
        if "notes" in parts:
            return "notes"
        if len(parts) >= 4 and parts[3] == "custom_fields":
            if len(parts) >= 5 and parts[4] == "groups":
                return "custom_field_groups"
            return "custom_fields"
        if len(parts) >= 4 and parts[3] == "tags":
            return "tags"
        if resource == "leads":
            if len(parts) >= 4 and parts[3] == "pipelines":
                return "pipeline_statuses" if "statuses" in parts else "pipelines"
            if len(parts) >= 4 and parts[3] == "loss_reasons":
                return "loss_reasons"
            if len(parts) >= 4 and parts[3] == "unsorted":
                return "unsorted"
        if resource == "catalogs" and len(parts) >= 5 and parts[4] == "elements":
            return "catalog_elements"
        if resource == "customers" and len(parts) >= 5 and parts[4] == "transactions":
            return "customer_transactions"
        if len(parts) >= 5 and parts[4] == "link":
            return "links"
        return resource

    return resource


def ensure_request_allowed(method: str, path_or_url: str) -> None:
    method = method.upper()
    if method in READ_METHODS:
        return
    if method not in WRITE_METHODS:
        raise McpError(-32602, f"Unsupported HTTP method: {method}.")

    policy = write_policy()
    resource = classify_api_resource(path_or_url)
    if policy["readonly"]:
        raise McpError(
            -32003,
            f"Write operation denied by AMOCRM_READONLY=true. Resource '{resource}', method {method}.",
        )

    denylist = set(policy["write_denylist"])
    if "*" in denylist or resource in denylist:
        raise McpError(
            -32003,
            f"Write operation denied by AMOCRM_WRITE_DENYLIST for resource '{resource}', method {method}.",
        )

    allowlist = set(policy["write_allowlist"])
    if allowlist and "*" not in allowlist and resource not in allowlist:
        raise McpError(
            -32003,
            f"Write operation denied because resource '{resource}' is not in AMOCRM_WRITE_ALLOWLIST.",
        )


def config_status() -> dict[str, Any]:
    env_status = load_local_env()
    token_env, token = first_env(TOKEN_ENV_NAMES)
    return {
        "base_url": configured_base_url(),
        "base_url_configured": configured_base_url() is not None,
        "token_configured": bool(token),
        "token_env": token_env,
        "timeout": float(os.environ.get("AMOCRM_TIMEOUT", "30")),
        "rate_limit_seconds": rate_limit_interval_seconds(),
        "rate_limit_lock_file": rate_limit_lock_path(),
        "local_env": env_status,
        "write_policy": write_policy(),
        "auth_mode": "long-lived Bearer token; no OAuth refresh flow",
    }


def text_response(value: Any, is_error: bool = False) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def json_rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def json_rpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def ensure_object(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpError(-32602, f"{name} must be an object.")
    return value


def ensure_array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise McpError(-32602, f"{name} must be an array.")
    return value


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    if size < 1 or size > 250:
        raise McpError(-32602, "chunk_size must be between 1 and 250.")
    return [items[index : index + size] for index in range(0, len(items), size)]


def ensure_entity_type(entity_type: str, allowed: tuple[str, ...], name: str = "entity_type") -> str:
    if entity_type not in allowed:
        raise McpError(-32602, f"Unsupported {name}: {entity_type}. Allowed: {', '.join(allowed)}.")
    return entity_type


def safe_id(value: Any, name: str) -> str:
    if isinstance(value, bool) or value is None:
        raise McpError(-32602, f"{name} is required.")
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise McpError(-32602, f"{name} contains unsupported characters.")
    return text


def render_path(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise McpError(-32602, f"Missing path parameter: {key}.")
        return urllib.parse.quote(safe_id(values[key], key), safe="")

    return re.sub(r"\{([A-Za-z0-9_]+)\}", replace, template)


def build_url(config: AmoConfig, path: str, params: dict[str, Any] | None = None) -> str:
    if not isinstance(path, str) or not path:
        raise McpError(-32602, "path must be a non-empty string.")

    if path.startswith("http://") or path.startswith("https://"):
        if not path.startswith(config.base_url + "/"):
            raise McpError(-32602, "Absolute URLs must belong to the configured amoCRM account.")
        url = path
    else:
        if not path.startswith("/api/") and path != "/oauth2/access_token":
            raise McpError(-32602, "Only amoCRM API paths are allowed, for example /api/v4/leads.")
        url = config.base_url + path

    params = {k: v for k, v in (params or {}).items() if v is not None}
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode(params, doseq=True)
    return url


def parse_response(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type or text[:1] in ("{", "["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def amocrm_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: Any | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = load_config()
    method = method.upper()
    if method not in HTTP_METHODS:
        raise McpError(-32602, f"Unsupported HTTP method: {method}.")

    url = build_url(config, path, params)
    ensure_request_allowed(method, url)
    headers = {
        "Accept": "application/hal+json, application/json",
        "Authorization": f"Bearer {config.token}",
        "User-Agent": f"{SERVER_NAME}/{__version__}",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(url=url, data=payload, headers=headers, method=method)
    acquire_rate_limit_slot()
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            return {
                "ok": 200 <= response.status <= 204,
                "status": response.status,
                "url": url,
                "content_type": content_type,
                "data": parse_response(raw, content_type),
                "elapsed_ms": round((time.time() - started) * 1000),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        content_type = exc.headers.get("Content-Type", "")
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "content_type": content_type,
            "data": parse_response(raw, content_type),
            "elapsed_ms": round((time.time() - started) * 1000),
        }
    except urllib.error.URLError as exc:
        raise McpError(-32002, f"Network error while calling amoCRM: {exc.reason}") from exc


def tool_describe_capabilities(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "server": SERVER_NAME,
        "version": __version__,
        "auth": {
            "type": "long-lived Bearer token",
            "env": {
                "base_url": "AMOCRM_BASE_URL=https://example.amocrm.ru or AMOCRM_SUBDOMAIN=example",
                "token": "AMOCRM_LONG_LIVED_TOKEN",
                "domain_suffix": "AMOCRM_DOMAIN_SUFFIX=amocrm.ru by default; use amocrm.com when needed",
            },
            "oauth": "not used",
        },
        "coverage": {
            "structured_tools": [
                "account",
                "entities",
                "resource_action",
                "notes",
                "links",
                "tags",
                "custom_fields",
                "pipelines",
                "catalog_elements",
                "customer_transactions",
                "pagination",
            ],
            "generic_escape_hatch": "amocrm_api_request can call any /api/... endpoint on the configured account.",
            "resources": RESOURCE_ACTIONS,
        },
        "docs_checked": [
            "https://www.amocrm.ru/developers/content/crm_platform/api-reference",
            "https://www.amocrm.ru/developers/content/oauth/step-by-step",
            "https://www.amocrm.ru/developers/content/crm_platform/account-info",
            "https://www.amocrm.ru/developers/content/crm_platform/leads-api",
            "https://www.amocrm.ru/developers/content/crm_platform/contacts-api",
            "https://www.amocrm.ru/developers/content/crm_platform/companies-api",
            "https://www.amocrm.ru/developers/content/crm_platform/tasks-api",
            "https://www.amocrm.ru/developers/content/crm_platform/custom-fields",
        ],
    }


def tool_config_check(_: dict[str, Any]) -> dict[str, Any]:
    return config_status()


def tool_api_request(args: dict[str, Any]) -> dict[str, Any]:
    method = str(args.get("method", "GET")).upper()
    path = args.get("path")
    params = ensure_object(args.get("params"), "params")
    body = args.get("json")
    headers = ensure_object(args.get("headers"), "headers")
    allowed_headers = {
        key: str(value)
        for key, value in headers.items()
        if key.lower() in {"idempotency-key", "x-request-id", "if-match"}
    }
    return amocrm_request(method, path, params=params, body=body, extra_headers=allowed_headers)


def tool_get_account(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    with_values = args.get("with")
    if with_values:
        params["with"] = ",".join(with_values) if isinstance(with_values, list) else str(with_values)
    return amocrm_request("GET", "/api/v4/account", params=params)


def entity_path(entity_type: str, entity_id: Any | None = None) -> str:
    ensure_entity_type(entity_type, ENTITY_COLLECTIONS)
    path = f"/api/v4/{entity_type}"
    if entity_id is not None:
        path += "/" + urllib.parse.quote(safe_id(entity_id, "id"), safe="")
    return path


def tool_list_entities(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    params = ensure_object(args.get("params"), "params")
    return amocrm_request("GET", entity_path(entity_type), params=params)


def tool_get_entity(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    params = ensure_object(args.get("params"), "params")
    return amocrm_request("GET", entity_path(entity_type, args.get("id")), params=params)


def tool_create_entities(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    items = ensure_array(args.get("items"), "items")
    return amocrm_request("POST", entity_path(entity_type), body=items)


def tool_update_entities(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    items = ensure_array(args.get("items"), "items")
    return amocrm_request("PATCH", entity_path(entity_type), body=items)


def tool_update_entity(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    data = ensure_object(args.get("data"), "data")
    return amocrm_request("PATCH", entity_path(entity_type, args.get("id")), body=data)


def batch_request(
    method: str,
    path: str,
    items: list[Any],
    chunk_size: int,
    params: dict[str, Any] | None = None,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    chunks = chunked(items, chunk_size)
    responses: list[dict[str, Any]] = []
    created_or_updated: list[Any] = []
    ok = True

    for index, chunk in enumerate(chunks, 1):
        response = amocrm_request(method, path, params=params, body=chunk)
        data = response.get("data")
        embedded = data.get("_embedded", {}) if isinstance(data, dict) else {}
        if isinstance(embedded, dict):
            for value in embedded.values():
                if isinstance(value, list):
                    created_or_updated.extend(value)

        responses.append(
            {
                "chunk": index,
                "items_count": len(chunk),
                "ok": response.get("ok"),
                "status": response.get("status"),
                "data": data,
            }
        )
        if not response.get("ok"):
            ok = False
            if stop_on_error:
                break

    processed_count = sum(item["items_count"] for item in responses)
    return {
        "ok": ok,
        "method": method,
        "path": path,
        "chunk_size": chunk_size,
        "total_items": len(items),
        "processed_items": processed_count,
        "chunks_total": len(chunks),
        "chunks_processed": len(responses),
        "items": created_or_updated,
        "responses": responses,
        "stopped_on_error": stop_on_error and not ok,
    }


def tool_batch_request(args: dict[str, Any]) -> dict[str, Any]:
    method = str(args.get("method", "POST")).upper()
    if method not in ("POST", "PATCH"):
        raise McpError(-32602, "batch_request method must be POST or PATCH.")
    path = str(args.get("path", ""))
    items = ensure_array(args.get("items"), "items")
    params = ensure_object(args.get("params"), "params")
    chunk_size = int(args.get("chunk_size", 50))
    stop_on_error = bool(args.get("stop_on_error", True))
    return batch_request(method, path, items, chunk_size, params=params, stop_on_error=stop_on_error)


def tool_batch_create_entities(args: dict[str, Any]) -> dict[str, Any]:
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), ENTITY_COLLECTIONS)
    items = ensure_array(args.get("items"), "items")
    chunk_size = int(args.get("chunk_size", 50))
    stop_on_error = bool(args.get("stop_on_error", True))
    return batch_request("POST", entity_path(entity_type), items, chunk_size, stop_on_error=stop_on_error)


def nested_entity_path(entity_type: str, entity_id: Any, suffix: str) -> str:
    return f"/api/v4/{ensure_entity_type(entity_type, NOTE_ENTITIES)}/{safe_id(entity_id, 'entity_id')}/{suffix}"


def tool_entity_notes(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), NOTE_ENTITIES)
    entity_id = args.get("entity_id")
    params = ensure_object(args.get("params"), "params")
    if action == "list":
        return amocrm_request("GET", nested_entity_path(entity_type, entity_id, "notes"), params=params)
    if action == "create":
        return amocrm_request("POST", nested_entity_path(entity_type, entity_id, "notes"), body=ensure_array(args.get("items"), "items"))
    if action == "update_one":
        data = ensure_object(args.get("data"), "data")
        note_id = safe_id(args.get("note_id"), "note_id")
        return amocrm_request("PATCH", nested_entity_path(entity_type, entity_id, f"notes/{note_id}"), body=data)
    raise McpError(-32602, "notes action must be one of: list, create, update_one.")


def tool_entity_links(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "link"))
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), LINK_ENTITIES)
    entity_id = args.get("entity_id")
    items = ensure_array(args.get("items"), "items")
    if action == "link":
        return amocrm_request("POST", f"/api/v4/{entity_type}/{safe_id(entity_id, 'entity_id')}/link", body=items)
    if action == "unlink":
        return amocrm_request("DELETE", f"/api/v4/{entity_type}/{safe_id(entity_id, 'entity_id')}/link", body=items)
    raise McpError(-32602, "links action must be one of: link, unlink.")


def tool_entity_tags(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), TAG_ENTITIES)
    params = ensure_object(args.get("params"), "params")
    path = f"/api/v4/{entity_type}/tags"
    if action == "list":
        return amocrm_request("GET", path, params=params)
    if action == "create":
        return amocrm_request("POST", path, body=ensure_array(args.get("items"), "items"))
    raise McpError(-32602, "tags action must be one of: list, create.")


def tool_custom_fields(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    entity_type = ensure_entity_type(str(args.get("entity_type", "")), CUSTOM_FIELD_ENTITIES)
    field_id = args.get("field_id")
    params = ensure_object(args.get("params"), "params")
    base = f"/api/v4/{entity_type}/custom_fields"

    if action == "list":
        return amocrm_request("GET", base, params=params)
    if action == "get":
        return amocrm_request("GET", f"{base}/{safe_id(field_id, 'field_id')}", params=params)
    if action == "create":
        return amocrm_request("POST", base, body=ensure_array(args.get("items"), "items"))
    if action == "update":
        return amocrm_request("PATCH", base, body=ensure_array(args.get("items"), "items"))
    if action == "update_one":
        return amocrm_request("PATCH", f"{base}/{safe_id(field_id, 'field_id')}", body=ensure_object(args.get("data"), "data"))
    if action == "delete":
        return amocrm_request("DELETE", f"{base}/{safe_id(field_id, 'field_id')}")
    raise McpError(-32602, "custom_fields action must be one of: list, get, create, update, update_one, delete.")


def tool_pipelines(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    pipeline_id = args.get("pipeline_id")
    status_id = args.get("status_id")
    params = ensure_object(args.get("params"), "params")
    base = "/api/v4/leads/pipelines"

    if action == "list":
        return amocrm_request("GET", base, params=params)
    if action == "get":
        return amocrm_request("GET", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}", params=params)
    if action == "create":
        return amocrm_request("POST", base, body=ensure_array(args.get("items"), "items"))
    if action == "update":
        return amocrm_request("PATCH", base, body=ensure_array(args.get("items"), "items"))
    if action == "update_one":
        return amocrm_request("PATCH", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}", body=ensure_object(args.get("data"), "data"))
    if action == "delete":
        return amocrm_request("DELETE", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}")
    if action == "list_statuses":
        return amocrm_request("GET", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}/statuses", params=params)
    if action == "create_statuses":
        return amocrm_request("POST", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}/statuses", body=ensure_array(args.get("items"), "items"))
    if action == "update_statuses":
        return amocrm_request("PATCH", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}/statuses", body=ensure_array(args.get("items"), "items"))
    if action == "delete_status":
        return amocrm_request("DELETE", f"{base}/{safe_id(pipeline_id, 'pipeline_id')}/statuses/{safe_id(status_id, 'status_id')}")
    raise McpError(
        -32602,
        "pipelines action must be one of: list, get, create, update, update_one, delete, list_statuses, create_statuses, update_statuses, delete_status.",
    )


def tool_catalog_elements(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    catalog_id = safe_id(args.get("catalog_id"), "catalog_id")
    element_id = args.get("element_id")
    params = ensure_object(args.get("params"), "params")
    base = f"/api/v4/catalogs/{catalog_id}/elements"

    if action == "list":
        return amocrm_request("GET", base, params=params)
    if action == "get":
        return amocrm_request("GET", f"{base}/{safe_id(element_id, 'element_id')}", params=params)
    if action == "create":
        return amocrm_request("POST", base, body=ensure_array(args.get("items"), "items"))
    if action == "update":
        return amocrm_request("PATCH", base, body=ensure_array(args.get("items"), "items"))
    if action == "update_one":
        return amocrm_request("PATCH", f"{base}/{safe_id(element_id, 'element_id')}", body=ensure_object(args.get("data"), "data"))
    raise McpError(-32602, "catalog_elements action must be one of: list, get, create, update, update_one.")


def tool_customer_transactions(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "list"))
    customer_id = safe_id(args.get("customer_id"), "customer_id")
    transaction_id = args.get("transaction_id")
    params = ensure_object(args.get("params"), "params")
    base = f"/api/v4/customers/{customer_id}/transactions"

    if action == "list":
        return amocrm_request("GET", base, params=params)
    if action == "create":
        return amocrm_request("POST", base, body=ensure_array(args.get("items"), "items"))
    if action == "delete":
        return amocrm_request("DELETE", f"{base}/{safe_id(transaction_id, 'transaction_id')}")
    raise McpError(-32602, "customer_transactions action must be one of: list, create, delete.")


def tool_resource_action(args: dict[str, Any]) -> dict[str, Any]:
    resource = str(args.get("resource", ""))
    action = str(args.get("action", ""))
    path_params = ensure_object(args.get("path_params"), "path_params")
    params = ensure_object(args.get("params"), "params")
    body = args.get("json")

    resource_spec = RESOURCE_ACTIONS.get(resource)
    if not resource_spec:
        raise McpError(-32602, f"Unknown resource: {resource}.")
    action_spec = resource_spec.get(action)
    if not action_spec:
        raise McpError(-32602, f"Unknown action '{action}' for resource '{resource}'.")

    path = render_path(action_spec["path"], path_params)
    return amocrm_request(action_spec["method"], path, params=params, body=body)


def tool_paginate(args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path", ""))
    params = ensure_object(args.get("params"), "params")
    max_pages = int(args.get("max_pages", 20))
    if max_pages < 1 or max_pages > 200:
        raise McpError(-32602, "max_pages must be between 1 and 200.")
    limit = int(args.get("limit", params.get("limit", 250)))
    if limit < 1 or limit > 250:
        raise McpError(-32602, "limit must be between 1 and 250.")

    results: list[Any] = []
    pages: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        page_params = dict(params)
        page_params["page"] = page
        page_params["limit"] = limit
        response = amocrm_request("GET", path, params=page_params)
        pages.append({"page": page, "status": response["status"], "ok": response["ok"]})
        if not response["ok"]:
            return {"ok": False, "pages": pages, "items": results, "last_response": response}

        data = response.get("data")
        embedded = data.get("_embedded", {}) if isinstance(data, dict) else {}
        if isinstance(embedded, dict) and embedded:
            first_collection = next((value for value in embedded.values() if isinstance(value, list)), None)
            if first_collection is not None:
                results.extend(first_collection)

        links = data.get("_links", {}) if isinstance(data, dict) else {}
        if not isinstance(links, dict) or "next" not in links:
            return {"ok": True, "pages": pages, "items": results, "last_response": response}

    return {"ok": True, "truncated": True, "pages": pages, "items": results}


def schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": additional_properties,
    }


def enum_schema(values: tuple[str, ...] | list[str], description: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "enum": list(values)}
    if description:
        result["description"] = description
    return result


def array_schema(description: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": {"type": "object", "additionalProperties": True}}
    if description:
        result["description"] = description
    return result


TOOLS: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], Any]]] = {
    "amocrm_describe_capabilities": (
        "Show available amoCRM resources, actions, auth mode, and documentation coverage.",
        schema(),
        tool_describe_capabilities,
    ),
    "amocrm_config_check": (
        "Check whether amoCRM base URL and long-lived token environment variables are configured.",
        schema(),
        tool_config_check,
    ),
    "amocrm_api_request": (
        "Call any amoCRM /api/... endpoint on the configured account using the long-lived Bearer token.",
        schema(
            {
                "method": enum_schema(HTTP_METHODS),
                "path": {"type": "string", "description": "Path such as /api/v4/leads or full URL on the configured account."},
                "params": {"type": "object", "additionalProperties": True},
                "json": {"description": "JSON request body for POST/PATCH/DELETE when the endpoint expects it."},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            ["method", "path"],
        ),
        tool_api_request,
    ),
    "amocrm_batch_request": (
        "Send large POST/PATCH array payloads to any amoCRM /api/... endpoint in chunks. Use for mass create/update operations.",
        schema(
            {
                "method": enum_schema(("POST", "PATCH")),
                "path": {"type": "string", "description": "Path such as /api/v4/leads or /api/v4/tasks."},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema("Array payload split into chunked requests."),
                "chunk_size": {"type": "integer", "minimum": 1, "maximum": 250, "default": 50},
                "stop_on_error": {"type": "boolean", "default": True},
            },
            ["method", "path", "items"],
        ),
        tool_batch_request,
    ),
    "amocrm_get_account": (
        "Get account parameters. Use 'with' for amojo_id, users_groups, task_types, version, entity_names, datetime_settings, drive_url, is_api_filter_enabled, invoices_settings.",
        schema({"with": {"type": "array", "items": {"type": "string"}}}),
        tool_get_account,
    ),
    "amocrm_list_entities": (
        "List top-level amoCRM entities with query/filter/order params.",
        schema({"entity_type": enum_schema(ENTITY_COLLECTIONS), "params": {"type": "object", "additionalProperties": True}}, ["entity_type"]),
        tool_list_entities,
    ),
    "amocrm_get_entity": (
        "Get one top-level amoCRM entity by ID.",
        schema({"entity_type": enum_schema(ENTITY_COLLECTIONS), "id": {"type": ["integer", "string"]}, "params": {"type": "object", "additionalProperties": True}}, ["entity_type", "id"]),
        tool_get_entity,
    ),
    "amocrm_create_entities": (
        "Create one or more top-level entities. Body must be the amoCRM array payload.",
        schema({"entity_type": enum_schema(ENTITY_COLLECTIONS), "items": array_schema()}, ["entity_type", "items"]),
        tool_create_entities,
    ),
    "amocrm_batch_create_entities": (
        "Create many top-level entities through amoCRM array endpoints, automatically splitting items into chunks.",
        schema(
            {
                "entity_type": enum_schema(ENTITY_COLLECTIONS),
                "items": array_schema("Array of entity payloads to create."),
                "chunk_size": {"type": "integer", "minimum": 1, "maximum": 250, "default": 50},
                "stop_on_error": {"type": "boolean", "default": True},
            },
            ["entity_type", "items"],
        ),
        tool_batch_create_entities,
    ),
    "amocrm_update_entities": (
        "Batch update top-level entities. Body must be the amoCRM array payload with IDs.",
        schema({"entity_type": enum_schema(ENTITY_COLLECTIONS), "items": array_schema()}, ["entity_type", "items"]),
        tool_update_entities,
    ),
    "amocrm_update_entity": (
        "Update one top-level entity by ID.",
        schema({"entity_type": enum_schema(ENTITY_COLLECTIONS), "id": {"type": ["integer", "string"]}, "data": {"type": "object", "additionalProperties": True}}, ["entity_type", "id", "data"]),
        tool_update_entity,
    ),
    "amocrm_entity_notes": (
        "List, create, or update notes on leads, contacts, companies, or customers.",
        schema(
            {
                "action": enum_schema(("list", "create", "update_one")),
                "entity_type": enum_schema(NOTE_ENTITIES),
                "entity_id": {"type": ["integer", "string"]},
                "note_id": {"type": ["integer", "string"]},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema("Array of note payloads for create."),
                "data": {"type": "object", "additionalProperties": True},
            },
            ["action", "entity_type", "entity_id"],
        ),
        tool_entity_notes,
    ),
    "amocrm_entity_links": (
        "Link or unlink entities using amoCRM link payloads.",
        schema(
            {
                "action": enum_schema(("link", "unlink")),
                "entity_type": enum_schema(LINK_ENTITIES),
                "entity_id": {"type": ["integer", "string"]},
                "items": array_schema("Array of _to_entity_id/_to_entity_type link payloads."),
            },
            ["action", "entity_type", "entity_id", "items"],
        ),
        tool_entity_links,
    ),
    "amocrm_entity_tags": (
        "List or create tags for leads, contacts, companies, or customers.",
        schema(
            {
                "action": enum_schema(("list", "create")),
                "entity_type": enum_schema(TAG_ENTITIES),
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema("Array of tag payloads for create."),
            },
            ["action", "entity_type"],
        ),
        tool_entity_tags,
    ),
    "amocrm_custom_fields": (
        "Manage custom fields for leads, contacts, companies, customers, or catalogs.",
        schema(
            {
                "action": enum_schema(("list", "get", "create", "update", "update_one", "delete")),
                "entity_type": enum_schema(CUSTOM_FIELD_ENTITIES),
                "field_id": {"type": ["integer", "string"]},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema(),
                "data": {"type": "object", "additionalProperties": True},
            },
            ["action", "entity_type"],
        ),
        tool_custom_fields,
    ),
    "amocrm_pipelines": (
        "Manage lead pipelines and pipeline statuses.",
        schema(
            {
                "action": enum_schema(("list", "get", "create", "update", "update_one", "delete", "list_statuses", "create_statuses", "update_statuses", "delete_status")),
                "pipeline_id": {"type": ["integer", "string"]},
                "status_id": {"type": ["integer", "string"]},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema(),
                "data": {"type": "object", "additionalProperties": True},
            },
            ["action"],
        ),
        tool_pipelines,
    ),
    "amocrm_catalog_elements": (
        "Manage elements inside an amoCRM catalog/list.",
        schema(
            {
                "action": enum_schema(("list", "get", "create", "update", "update_one")),
                "catalog_id": {"type": ["integer", "string"]},
                "element_id": {"type": ["integer", "string"]},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema(),
                "data": {"type": "object", "additionalProperties": True},
            },
            ["action", "catalog_id"],
        ),
        tool_catalog_elements,
    ),
    "amocrm_customer_transactions": (
        "List, add, or delete customer transactions.",
        schema(
            {
                "action": enum_schema(("list", "create", "delete")),
                "customer_id": {"type": ["integer", "string"]},
                "transaction_id": {"type": ["integer", "string"]},
                "params": {"type": "object", "additionalProperties": True},
                "items": array_schema(),
            },
            ["action", "customer_id"],
        ),
        tool_customer_transactions,
    ),
    "amocrm_resource_action": (
        "Call a documented amoCRM resource/action from the built-in resource map.",
        schema(
            {
                "resource": enum_schema(tuple(RESOURCE_ACTIONS.keys())),
                "action": {"type": "string"},
                "path_params": {"type": "object", "additionalProperties": True},
                "params": {"type": "object", "additionalProperties": True},
                "json": {"description": "JSON request body exactly as amoCRM expects."},
            },
            ["resource", "action"],
        ),
        tool_resource_action,
    ),
    "amocrm_paginate": (
        "Fetch multiple pages from a GET collection endpoint and merge the first embedded list.",
        schema(
            {
                "path": {"type": "string"},
                "params": {"type": "object", "additionalProperties": True},
                "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            ["path"],
        ),
        tool_paginate,
    ),
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": description, "inputSchema": input_schema}
        for name, (description, input_schema, _handler) in TOOLS.items()
    ]


def handle_tool_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = ensure_object(params.get("arguments"), "arguments")
    if name not in TOOLS:
        raise McpError(-32601, f"Unknown tool: {name}")
    handler = TOOLS[name][2]
    try:
        return text_response(handler(args))
    except McpError as exc:
        return text_response({"error": exc.message, "data": exc.data}, is_error=True)
    except Exception as exc:  # noqa: BLE001 - MCP tools should report failures as tool output.
        return text_response({"error": str(exc), "traceback": traceback.format_exc()}, is_error=True)


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = ensure_object(message.get("params"), "params")

    if request_id is None:
        return None

    if method == "initialize":
        return json_rpc_result(
            request_id,
            {
                "protocolVersion": API_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        )
    if method == "ping":
        return json_rpc_result(request_id, {})
    if method == "tools/list":
        return json_rpc_result(request_id, {"tools": list_tools()})
    if method == "tools/call":
        return json_rpc_result(request_id, handle_tool_call(params))

    raise McpError(-32601, f"Method not found: {method}")


def serve() -> None:
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        request_id = None
        try:
            message = json.loads(line)
            request_id = message.get("id")
            response = handle_request(message)
        except McpError as exc:
            response = json_rpc_error(request_id, exc.code, exc.message, exc.data)
        except json.JSONDecodeError as exc:
            response = json_rpc_error(None, -32700, "Parse error", str(exc))
        except Exception as exc:  # noqa: BLE001 - keep MCP server alive.
            response = json_rpc_error(request_id, -32603, str(exc), traceback.format_exc())

        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def main() -> None:
    serve()
