from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools.base import Tool


ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
MAX_TOOL_NAME_LENGTH = 64


@dataclass(frozen=True)
class MCPServerSpec:
    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolSpec:
    server_name: str
    remote_name: str
    local_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPConnection:
    spec: MCPServerSpec
    session: Any
    stack: AsyncExitStack
    tools: list[MCPToolSpec] = field(default_factory=list)


@dataclass
class MCPServerStatus:
    name: str
    transport: str
    status: str
    tools: list[str] = field(default_factory=list)
    error: str | None = None


class MCPToolAdapter(Tool):
    def __init__(self, manager: "MCPClientManager", spec: MCPToolSpec) -> None:
        self._manager = manager
        self._spec = spec

    @property
    def name(self) -> str:
        return self._spec.local_name

    @property
    def description(self) -> str:
        base = self._spec.description or "MCP tool"
        return f"[MCP:{self._spec.server_name}] {base}"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._spec.input_schema

    def execute(self, **kwargs: Any) -> str:
        return self._manager.call_tool(
            self._spec.server_name,
            self._spec.remote_name,
            kwargs,
        )


class MCPClientManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.statuses: dict[str, MCPServerStatus] = {}
        self.connections: dict[str, MCPConnection] = {}
        self.tool_specs: list[MCPToolSpec] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        specs = self._load_specs()
        if not specs:
            return

        self._start_loop()
        for spec in specs:
            self.statuses[spec.name] = MCPServerStatus(
                name=spec.name,
                transport=spec.transport,
                status="connecting",
            )
            try:
                self._run("connect_server", spec, timeout=30)
            except Exception as exc:
                self.statuses[spec.name] = MCPServerStatus(
                    name=spec.name,
                    transport=spec.transport,
                    status="error",
                    error=str(exc),
                )

    def tools(self) -> list[MCPToolAdapter]:
        return [MCPToolAdapter(self, spec) for spec in self.tool_specs]

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        return self._run("call_tool", server_name, tool_name, arguments, timeout=120)

    def report(self) -> str:
        if not self.config_path.exists():
            return f"No MCP config found at {self.config_path}."
        if not self.statuses:
            return "No MCP servers configured."

        lines = []
        for name in sorted(self.statuses):
            status = self.statuses[name]
            line = f"- {name} ({status.transport}): {status.status}"
            if status.error:
                line += f" - {status.error}"
            lines.append(line)
            for tool_name in status.tools:
                lines.append(f"  - {tool_name}")
        return "\n".join(lines)

    def close(self) -> None:
        if not self._loop:
            return
        try:
            self._run("close_all", timeout=10)
            self._run("shutdown", timeout=10)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None

    def _load_specs(self) -> list[MCPServerSpec]:
        if not self.config_path.exists():
            return []

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self.statuses["<config>"] = MCPServerStatus(
                name="<config>",
                transport="config",
                status="error",
                error=f"invalid JSON: {exc}",
            )
            return []

        raw_servers = data.get("mcpServers", data)
        if not isinstance(raw_servers, dict):
            self.statuses["<config>"] = MCPServerStatus(
                name="<config>",
                transport="config",
                status="error",
                error="expected an object at mcpServers",
            )
            return []

        specs: list[MCPServerSpec] = []
        for name, raw_config in raw_servers.items():
            if not isinstance(raw_config, dict):
                self.statuses[name] = MCPServerStatus(
                    name=name,
                    transport="config",
                    status="error",
                    error="server config must be an object",
                )
                continue
            try:
                config = _interpolate(raw_config, f"mcpServers.{name}")
                specs.append(_spec_from_config(name, config))
            except Exception as exc:
                transport = str(raw_config.get("transport") or "config")
                self.statuses[name] = MCPServerStatus(
                    name=name,
                    transport=transport,
                    status="error",
                    error=str(exc),
                )
        return specs

    def _start_loop(self) -> None:
        if self._loop:
            return

        ready = threading.Event()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._queue = asyncio.Queue()
            loop.create_task(self._worker())
            ready.set()
            loop.run_forever()
            loop.close()

        self._thread = threading.Thread(target=run_loop, name="mcp-client-loop", daemon=True)
        self._thread.start()
        ready.wait(timeout=5)
        if not self._loop:
            raise RuntimeError("failed to start MCP event loop")

    def _run(self, operation: str, *args: Any, timeout: float):
        if not self._loop or not self._queue:
            raise RuntimeError("MCP event loop is not running")
        future: Future = Future()
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            (operation, args, future),
        )
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            operation, args, future = await self._queue.get()
            if future.cancelled():
                continue
            try:
                if operation == "shutdown":
                    future.set_result(None)
                    return
                if operation == "connect_server":
                    async with asyncio.timeout(30):
                        result = await self._connect_server(*args)
                elif operation == "call_tool":
                    async with asyncio.timeout(120):
                        result = await self._call_tool(*args)
                elif operation == "close_all":
                    async with asyncio.timeout(10):
                        result = await self._close_all()
                else:
                    raise ValueError(f"unknown MCP worker operation {operation!r}")
                if not future.cancelled():
                    future.set_result(result)
            except BaseException as exc:
                if not future.cancelled():
                    future.set_exception(exc)

    async def _connect_server(self, spec: MCPServerSpec) -> None:
        stack = AsyncExitStack()
        try:
            if spec.transport == "stdio":
                read_stream, write_stream = await stack.enter_async_context(
                    _stdio_transport(spec)
                )
            elif spec.transport == "streamable_http":
                transport = await stack.enter_async_context(_http_transport(spec))
                read_stream, write_stream = transport[0], transport[1]
            else:
                raise ValueError(f"unsupported MCP transport {spec.transport!r}")

            from mcp import ClientSession

            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            result = await session.list_tools()
            remote_tools = getattr(result, "tools", []) or []

            tool_specs: list[MCPToolSpec] = []
            used_names = {tool.local_name for tool in self.tool_specs}
            for remote_tool in remote_tools:
                remote_name = str(getattr(remote_tool, "name", ""))
                if not remote_name:
                    continue
                local_name = _unique_tool_name(spec.name, remote_name, used_names)
                used_names.add(local_name)
                schema = _schema_from_tool(remote_tool)
                description = str(getattr(remote_tool, "description", "") or "")
                tool_specs.append(
                    MCPToolSpec(
                        server_name=spec.name,
                        remote_name=remote_name,
                        local_name=local_name,
                        description=description,
                        input_schema=schema,
                    )
                )

            with self._lock:
                self.connections[spec.name] = MCPConnection(
                    spec=spec,
                    session=session,
                    stack=stack,
                    tools=tool_specs,
                )
                self.tool_specs.extend(tool_specs)
                self.statuses[spec.name] = MCPServerStatus(
                    name=spec.name,
                    transport=spec.transport,
                    status="connected",
                    tools=[tool.local_name for tool in tool_specs],
                )
        except Exception:
            await stack.aclose()
            raise

    async def _call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        connection = self.connections.get(server_name)
        if connection is None:
            return f"Error: MCP server {server_name!r} is not connected."

        result = await connection.session.call_tool(tool_name, arguments=arguments)
        return _format_tool_result(server_name, tool_name, result)

    async def _close_all(self) -> None:
        connections = list(self.connections.values())
        self.connections.clear()
        self.tool_specs.clear()
        for connection in reversed(connections):
            await connection.stack.aclose()


def _spec_from_config(name: str, config: dict[str, Any]) -> MCPServerSpec:
    transport = config.get("transport")
    if not transport:
        if config.get("command"):
            transport = "stdio"
        elif config.get("url"):
            transport = "streamable_http"
        else:
            raise ValueError("missing transport; provide command or url")

    transport = str(transport).strip()
    if transport in {"http", "streamable-http"}:
        transport = "streamable_http"

    if transport == "stdio":
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("stdio server requires command")
        args = config.get("args", [])
        if not isinstance(args, list):
            raise ValueError("stdio args must be an array")
        env = config.get("env", {})
        if not isinstance(env, dict):
            raise ValueError("stdio env must be an object")
        return MCPServerSpec(
            name=name,
            transport=transport,
            command=command,
            args=[str(item) for item in args],
            env={str(key): str(value) for key, value in env.items()},
        )

    if transport == "streamable_http":
        url = config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("streamable_http server requires url")
        headers = config.get("headers", {})
        if not isinstance(headers, dict):
            raise ValueError("streamable_http headers must be an object")
        return MCPServerSpec(
            name=name,
            transport=transport,
            url=url,
            headers={str(key): str(value) for key, value in headers.items()},
        )

    raise ValueError(f"unsupported transport {transport!r}")


def _interpolate(value: Any, path: str) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in os.environ:
                raise ValueError(f"missing environment variable {var_name!r} at {path}")
            return os.environ[var_name]

        return ENV_VAR_RE.sub(replace, value)
    if isinstance(value, list):
        return [_interpolate(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _interpolate(item, f"{path}.{key}") for key, item in value.items()}
    return value


def _stdio_transport(spec: MCPServerSpec):
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = None
    if spec.env:
        env = {**os.environ, **spec.env}
    params = StdioServerParameters(
        command=spec.command or "",
        args=spec.args,
        env=env,
    )
    return stdio_client(params)


def _http_transport(spec: MCPServerSpec):
    try:
        from mcp.client.streamable_http import streamablehttp_client as client_factory
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client as client_factory

    return client_factory(
        spec.url or "",
        headers=spec.headers or None,
    )


def _schema_from_tool(tool: Any) -> dict[str, Any]:
    schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "input_schema", None)
        or getattr(tool, "parameters", None)
        or {}
    )
    schema = _as_plain_data(schema)
    if not isinstance(schema, dict):
        schema = {}
    if not schema:
        return {"type": "object", "properties": {}, "required": []}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _as_plain_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return {key: _as_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_plain_data(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {
            key: _as_plain_data(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _unique_tool_name(server_name: str, tool_name: str, used_names: set[str]) -> str:
    base = f"mcp_{_sanitize(server_name)}_{_sanitize(tool_name)}"
    base = _fit_tool_name(base)
    candidate = base
    counter = 2
    while candidate in used_names:
        suffix = f"_{counter}"
        candidate = _fit_tool_name(base, suffix=suffix)
        counter += 1
    return candidate


def _sanitize(name: str) -> str:
    cleaned = TOOL_NAME_RE.sub("_", name.strip()).strip("_")
    return cleaned or "tool"


def _fit_tool_name(name: str, suffix: str = "") -> str:
    if len(name) + len(suffix) <= MAX_TOOL_NAME_LENGTH:
        return name + suffix
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    reserved = len(digest) + len(suffix) + 2
    return f"{name[: MAX_TOOL_NAME_LENGTH - reserved]}_{digest}{suffix}"


def _format_tool_result(server_name: str, tool_name: str, result: Any) -> str:
    is_error = bool(
        getattr(result, "isError", False)
        or getattr(result, "is_error", False)
    )
    parts: list[str] = []

    for item in getattr(result, "content", []) or []:
        item_type = getattr(item, "type", None)
        if item_type == "text":
            parts.append(str(getattr(item, "text", "")))
        else:
            parts.append(_to_json_text(_as_plain_data(item)))

    structured = (
        getattr(result, "structuredContent", None)
        or getattr(result, "structured_content", None)
    )
    if structured is not None:
        structured_text = _to_json_text(_as_plain_data(structured), indent=2)
        if not parts:
            parts.append(structured_text)
        else:
            parts.append(f"Structured content:\n{structured_text}")

    text = "\n".join(part for part in parts if part).strip()
    if not text:
        text = _to_json_text(_as_plain_data(result), indent=2)

    if is_error:
        return f"Error from MCP tool {server_name}.{tool_name}: {text}"
    return text


def _to_json_text(value: Any, indent: int | None = None) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=indent)
    except TypeError:
        return str(value)
