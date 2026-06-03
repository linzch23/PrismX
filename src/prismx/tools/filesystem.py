from __future__ import annotations

import difflib
import fnmatch
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .base import Tool, object_schema


IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
}


class WorkspaceTool(Tool):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def resolve(self, path: str) -> Path:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.workspace / target
        target = target.resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {path}") from exc
        return target

    def display(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(path)


class ReadFileTool(WorkspaceTool):
    name = "read_file"
    description = "Read a UTF-8 text file from the workspace with optional line pagination."
    read_only = True

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "1-based start line", "minimum": 1},
                "limit": {"type": "integer", "description": "line count", "minimum": 1},
            },
            required=["path"],
        )

    def execute(self, path: str, offset: int = 1, limit: int = 400, **_: Any) -> str:
        target = self.resolve(path)
        if not target.exists():
            return f"Error: file not found: {path}"
        if not target.is_file():
            return f"Error: not a file: {path}"
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"Error: cannot read binary file: {path}"
        start = max(offset, 1) - 1
        end = min(start + limit, len(lines))
        body = "\n".join(f"{idx + 1}| {line}" for idx, line in enumerate(lines[start:end], start))
        suffix = f"\n\n(Showing {start + 1}-{end} of {len(lines)} lines.)"
        return body + suffix


class WriteFileTool(WorkspaceTool):
    name = "write_file"
    description = "Write a UTF-8 text file in the workspace, replacing existing content."

    @property
    def parameters(self) -> dict:
        return object_schema(
            {"path": {"type": "string"}, "content": {"type": "string"}},
            required=["path", "content"],
        )

    def execute(self, path: str, content: str) -> str:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {self.display(target)}"


class EditFileTool(WorkspaceTool):
    name = "edit_file"
    description = (
        "Replace exact text in a workspace file. If old_text is empty and the file does not "
        "exist, create the file with new_text."
    )

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            required=["path", "old_text", "new_text"],
        )

    def execute(
        self, path: str, old_text: str, new_text: str, replace_all: bool = False, **_: Any
    ) -> str:
        target = self.resolve(path)
        if not target.exists():
            if old_text:
                return f"Error: file not found: {path}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_text, encoding="utf-8")
            return f"Created {self.display(target)}"

        text = target.read_text(encoding="utf-8")
        count = text.count(old_text)
        if old_text == "":
            return "Error: old_text cannot be empty for an existing file."
        if count == 0:
            best = difflib.get_close_matches(old_text, text.splitlines(), n=1)
            hint = f" Closest line: {best[0]!r}" if best else ""
            return f"Error: old_text not found in {path}.{hint}"
        if count > 1 and not replace_all:
            return f"Error: old_text occurs {count} times. Use replace_all=true or add context."
        updated = text.replace(old_text, new_text, -1 if replace_all else 1)
        target.write_text(updated, encoding="utf-8")
        return f"Edited {self.display(target)}"


class GlobTool(WorkspaceTool):
    name = "glob"
    description = "Find workspace files or directories matching a glob pattern."
    read_only = True

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string"},
                "entry_type": {"type": "string", "enum": ["files", "dirs", "both"]},
                "limit": {"type": "integer"},
            },
            required=["pattern"],
        )

    def execute(
        self, pattern: str, path: str = ".", entry_type: str = "files", limit: int = 200, **_: Any
    ) -> str:
        root = self.resolve(path)
        if not root.exists():
            return f"Error: path not found: {path}"
        include_files = entry_type in {"files", "both"}
        include_dirs = entry_type in {"dirs", "both"}
        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(item for item in dirnames if item not in IGNORE_DIRS)
            current = Path(dirpath)
            entries: list[Path] = []
            if include_dirs:
                entries.extend(current / item for item in dirnames)
            if include_files:
                entries.extend(current / item for item in filenames)
            for entry in entries:
                rel = self.display(entry)
                name = entry.name
                if "/" in pattern or pattern.startswith("**"):
                    ok = PurePosixPath(rel).match(pattern)
                else:
                    ok = fnmatch.fnmatch(name, pattern)
                if ok:
                    matches.append(rel)
                    if len(matches) >= limit:
                        return "\n".join(matches) + f"\n\n(Stopped at limit={limit}.)"
        return "\n".join(matches) if matches else "(No matches.)"


class GrepTool(WorkspaceTool):
    name = "grep"
    description = "Search UTF-8 workspace files for a regex pattern."
    read_only = True

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string"},
                "file_glob": {"type": "string"},
                "limit": {"type": "integer"},
            },
            required=["pattern"],
        )

    def execute(
        self, pattern: str, path: str = ".", file_glob: str = "*", limit: int = 200, **_: Any
    ) -> str:
        root = self.resolve(path)
        regex = re.compile(pattern)
        matches: list[str] = []
        files = [root] if root.is_file() else []
        if root.is_dir():
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(item for item in dirnames if item not in IGNORE_DIRS)
                files.extend(Path(dirpath) / item for item in sorted(filenames))
        for file_path in files:
            if not fnmatch.fnmatch(file_path.name, file_glob):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if regex.search(line):
                    matches.append(f"{self.display(file_path)}:{line_no}: {line}")
                    if len(matches) >= limit:
                        return "\n".join(matches) + f"\n\n(Stopped at limit={limit}.)"
        return "\n".join(matches) if matches else "(No matches.)"
