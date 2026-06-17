import json
import os
import tempfile
import unittest
from unittest import mock

from amocrm_mcp import server


class ServerTests(unittest.TestCase):
    def tearDown(self):
        server._PROCESS_LAST_REQUEST_AT = 0.0
        server.reset_local_env_cache()

    def test_build_url_from_subdomain_and_params(self):
        with mock.patch.dict(
            os.environ,
            {
                "AMOCRM_SUBDOMAIN": "example",
                "AMOCRM_LONG_LIVED_TOKEN": "token",
            },
            clear=True,
        ):
            config = server.load_config()
            url = server.build_url(
                config,
                "/api/v4/leads",
                {"limit": 2, "filter[id]": [1, 2], "empty": None},
            )

        self.assertEqual(
            url,
            "https://example.amocrm.ru/api/v4/leads?limit=2&filter%5Bid%5D=1&filter%5Bid%5D=2",
        )

    def test_resource_action_renders_path(self):
        path = server.render_path(
            "/api/v4/leads/pipelines/{pipeline_id}/statuses/{status_id}",
            {"pipeline_id": 10, "status_id": 20},
        )
        self.assertEqual(path, "/api/v4/leads/pipelines/10/statuses/20")

    def test_tools_list_contains_generic_request(self):
        names = {tool["name"] for tool in server.list_tools()}
        self.assertIn("amocrm_api_request", names)
        self.assertIn("amocrm_batch_request", names)
        self.assertIn("amocrm_batch_create_entities", names)
        self.assertIn("amocrm_resource_action", names)
        self.assertIn("amocrm_get_account", names)

    def test_initialize_json_rpc(self):
        response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "amocrm-mcp")

    def test_tool_call_without_token_returns_tool_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "amocrm_get_account",
                        "arguments": {},
                    },
                }
            )
        result = response["result"]
        self.assertTrue(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertIn("base URL is not configured", payload["error"])

    def test_rate_limit_defaults_to_one_second(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server.rate_limit_interval_seconds(), 1.0)

    def test_process_rate_limit_waits_between_requests(self):
        with mock.patch.object(server.time, "monotonic", side_effect=[100.0, 100.2, 101.0]):
            with mock.patch.object(server.time, "sleep") as sleep:
                server.acquire_process_rate_limit_slot(1.0)
                server.acquire_process_rate_limit_slot(1.0)

        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)
        self.assertEqual(server._PROCESS_LAST_REQUEST_AT, 101.0)

    def test_rate_limit_can_be_disabled_for_tests(self):
        with mock.patch.dict(os.environ, {"AMOCRM_RATE_LIMIT_SECONDS": "0"}, clear=True):
            with mock.patch.object(server.time, "sleep") as sleep:
                server.acquire_rate_limit_slot()
        sleep.assert_not_called()

    def test_chunked_splits_items(self):
        self.assertEqual(server.chunked([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_batch_request_sends_chunks(self):
        responses = [
            {"ok": True, "status": 200, "data": {"_embedded": {"tasks": [{"id": 1}, {"id": 2}]}}},
            {"ok": True, "status": 200, "data": {"_embedded": {"tasks": [{"id": 3}]}}},
        ]
        with mock.patch.object(server, "amocrm_request", side_effect=responses) as request:
            result = server.batch_request("POST", "/api/v4/tasks", [{"a": 1}, {"a": 2}, {"a": 3}], 2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["chunks_processed"], 2)
        self.assertEqual(result["processed_items"], 3)
        self.assertEqual(result["items"], [{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertEqual(request.call_args_list[0].kwargs["body"], [{"a": 1}, {"a": 2}])
        self.assertEqual(request.call_args_list[1].kwargs["body"], [{"a": 3}])

    def test_batch_request_stops_on_error(self):
        responses = [
            {"ok": False, "status": 400, "data": {"detail": "bad"}},
            {"ok": True, "status": 200, "data": {}},
        ]
        with mock.patch.object(server, "amocrm_request", side_effect=responses) as request:
            result = server.batch_request("POST", "/api/v4/tasks", [{"a": 1}, {"a": 2}], 1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["stopped_on_error"])
        self.assertEqual(result["chunks_processed"], 1)
        self.assertEqual(request.call_count, 1)

    def test_classify_api_resource(self):
        self.assertEqual(server.classify_api_resource("/api/v4/tasks"), "tasks")
        self.assertEqual(server.classify_api_resource("/api/v4/leads/pipelines"), "pipelines")
        self.assertEqual(server.classify_api_resource("/api/v4/leads/pipelines/1/statuses"), "pipeline_statuses")
        self.assertEqual(server.classify_api_resource("/api/v4/leads/custom_fields"), "custom_fields")
        self.assertEqual(server.classify_api_resource("/api/v4/leads/custom_fields/groups"), "custom_field_groups")
        self.assertEqual(server.classify_api_resource("/api/v4/leads/123/notes"), "notes")
        self.assertEqual(server.classify_api_resource("/api/v4/catalogs/1/elements"), "catalog_elements")

    def test_readonly_blocks_write_but_allows_read(self):
        with mock.patch.dict(os.environ, {"AMOCRM_READONLY": "true"}, clear=True):
            server.ensure_request_allowed("GET", "/api/v4/tasks")
            with self.assertRaises(server.McpError):
                server.ensure_request_allowed("POST", "/api/v4/tasks")

    def test_write_allowlist_allows_only_named_resources(self):
        with mock.patch.dict(os.environ, {"AMOCRM_WRITE_ALLOWLIST": "tasks,notes"}, clear=True):
            server.ensure_request_allowed("PATCH", "/api/v4/tasks")
            server.ensure_request_allowed("POST", "/api/v4/leads/notes")
            with self.assertRaises(server.McpError):
                server.ensure_request_allowed("PATCH", "/api/v4/leads/pipelines")

    def test_write_denylist_blocks_named_resources(self):
        with mock.patch.dict(os.environ, {"AMOCRM_WRITE_DENYLIST": "pipelines,pipeline_statuses,custom_fields"}, clear=True):
            server.ensure_request_allowed("PATCH", "/api/v4/tasks")
            with self.assertRaises(server.McpError):
                server.ensure_request_allowed("POST", "/api/v4/leads/pipelines")
            with self.assertRaises(server.McpError):
                server.ensure_request_allowed("PATCH", "/api/v4/leads/custom_fields")

    def test_local_env_file_overrides_mcp_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w", encoding="utf-8") as file:
                file.write(
                    "\n".join(
                        [
                            "AMOCRM_BASE_URL=https://local.amocrm.ru",
                            "AMOCRM_LONG_LIVED_TOKEN=local-token",
                            "AMOCRM_READONLY=true",
                            "AMOCRM_WRITE_ALLOWLIST=tasks,notes",
                            "IGNORED_SECRET=must-not-load",
                        ]
                    )
                )
            with mock.patch.dict(
                os.environ,
                {
                    "AMOCRM_ENV_FILE": env_path,
                    "AMOCRM_BASE_URL": "https://mcp.amocrm.ru",
                    "AMOCRM_LONG_LIVED_TOKEN": "mcp-token",
                },
                clear=True,
            ):
                server.reset_local_env_cache()
                config = server.load_config()
                status = server.config_status()

        self.assertEqual(config.base_url, "https://local.amocrm.ru")
        self.assertEqual(config.token, "local-token")
        self.assertTrue(status["write_policy"]["readonly"])
        self.assertEqual(status["write_policy"]["write_allowlist"], ["notes", "tasks"])
        self.assertEqual(status["local_env"]["source"], env_path)
        self.assertNotIn("IGNORED_SECRET", os.environ)

    def test_parse_env_file_supports_export_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".amocrm.env")
            with open(env_path, "w", encoding="utf-8") as file:
                file.write(
                    "\n".join(
                        [
                            'export AMOCRM_BASE_URL="https://quoted.amocrm.ru" # comment',
                            "AMOCRM_READONLY='true'",
                            "AMOCRM_WRITE_DENYLIST=pipelines,custom_fields",
                            "NOT_AMOCRM=value",
                        ]
                    )
                )
            values = server.parse_env_file(server.Path(env_path))

        self.assertEqual(values["AMOCRM_BASE_URL"], "https://quoted.amocrm.ru")
        self.assertEqual(values["AMOCRM_READONLY"], "true")
        self.assertEqual(values["AMOCRM_WRITE_DENYLIST"], "pipelines,custom_fields")
        self.assertNotIn("NOT_AMOCRM", values)


if __name__ == "__main__":
    unittest.main()
