"""Connection config for our MCP servers, shared by the agent and the tests."""
from __future__ import annotations

import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

from core.config import ROOT

MCP_SERVERS = {
    "macro": {
        "transport": "stdio",
        "command": sys.executable,                 # same venv Python that's running the app
        "args": ["-m", "mcp_servers.macro_server"],
        "cwd": str(ROOT),                          # so `-m mcp_servers...` resolves our packages
    },
}


def get_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(MCP_SERVERS)