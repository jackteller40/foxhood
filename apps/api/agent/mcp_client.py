"""Connection config for our MCP servers, shared by the agent and the tests."""
from __future__ import annotations

import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

from core.config import ROOT


def server_config() -> dict:
    # The MCP library starts stdio servers with only a few safe variables (PATH, HOME...) unless told
    # otherwise. Locally the server finds its keys in .env, but in production keys arrive as environment
    # variables (Secret Manager), so pass ours along: our own code, our own keys.
    return {
        "macro": {
            "transport": "stdio",
            "command": sys.executable,                 # same venv Python that's running the app
            "args": ["-m", "mcp_servers.macro_server"],
            "cwd": str(ROOT),                          # so `-m mcp_servers...` resolves our packages
            "env": dict(os.environ),
        },
    }


def get_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(server_config())
