from __future__ import annotations

import json
import os
import pathlib
import re
import sys


CONFIG_PATH = pathlib.Path.home() / ".codex" / "config.toml"
MARKER_RE = re.compile(r"^\[mcp_servers\.amocrm(?:\.env)?\]\s*$")
ANY_SECTION_RE = re.compile(r"^\[.+\]\s*$")


def remove_existing_amocrm_sections(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if MARKER_RE.match(lines[index]):
            index += 1
            while index < len(lines) and not ANY_SECTION_RE.match(lines[index]):
                index += 1
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output).rstrip() + "\n"


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def current_amocrm_env(text: str) -> dict[str, str]:
    try:
        import tomllib

        parsed = tomllib.loads(text)
        env = parsed.get("mcp_servers", {}).get("amocrm", {}).get("env", {})
        return env if isinstance(env, dict) else {}
    except Exception:
        return {}


def main() -> int:
    original = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
    existing_env = current_amocrm_env(original)
    stdin_text = sys.stdin.read()
    if stdin_text.strip():
        payload = json.loads(stdin_text)
    else:
        payload = {
            "base_url": os.environ.get("AMOCRM_BASE_URL") or existing_env.get("AMOCRM_BASE_URL"),
            "token": os.environ.get("AMOCRM_LONG_LIVED_TOKEN") or existing_env.get("AMOCRM_LONG_LIVED_TOKEN"),
            "command": os.environ.get("AMOCRM_MCP_COMMAND", "python3"),
            "cwd": os.environ.get("AMOCRM_MCP_CWD", str(pathlib.Path.cwd())),
        }
    base_url = payload["base_url"].rstrip("/")
    token = payload["token"]
    command = payload["command"]
    cwd = payload["cwd"]

    if not base_url.startswith("https://"):
        raise SystemExit("base_url must start with https://")
    if not token:
        raise SystemExit("token is required")

    updated = remove_existing_amocrm_sections(original)
    runner = str(pathlib.Path(cwd) / "scripts" / "run_amocrm_mcp.py")
    section = f"""
[mcp_servers.amocrm]
command = {quote(command)}
args = [ {quote(runner)} ]
cwd = {quote(cwd)}

[mcp_servers.amocrm.env]
AMOCRM_BASE_URL = {quote(base_url)}
AMOCRM_LONG_LIVED_TOKEN = {quote(token)}
AMOCRM_TIMEOUT = "30"
"""
    CONFIG_PATH.write_text(updated.rstrip() + "\n" + section.lstrip(), encoding="utf-8")
    print(f"configured amocrm MCP in {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
