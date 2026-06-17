import json
import os
import unittest
from unittest import mock

from amocrm_mcp import server


class ServerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
