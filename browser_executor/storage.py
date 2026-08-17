from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

SAFE_UNIX_SOCKET_PATH_BYTES = 90


class StorageError(RuntimeError):
    """Raised when private executor state cannot be created safely."""


def state_root() -> Path:
    raw = os.environ.get("LLM_WIKI_BROWSER_EXECUTOR_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    return Path.home() / ".local" / "state" / "llm-wiki" / "browser-execution"


def native_socket_path() -> Path:
    override = os.environ.get("LLM_WIKI_BROWSER_EXECUTOR_NATIVE_SOCKET")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    candidate = state_root() / "native-bridge.sock"
    if len(os.fsencode(str(candidate))) <= SAFE_UNIX_SOCKET_PATH_BYTES:
        return candidate
    digest = hashlib.sha256(str(candidate).encode("utf-8")).hexdigest()[:12]
    user_id = getattr(os, "getuid", lambda: 0)()
    return Path("/tmp") / f"llm-wiki-browser-{user_id}-{digest}" / "bridge.sock"


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise StorageError("executor state path is not a private directory")
    user_id = getattr(os, "getuid", lambda: metadata.st_uid)()
    if metadata.st_uid != user_id:
        raise StorageError("executor state path belongs to another user")
    path.chmod(0o700)


def ensure_socket_parent(socket_path: Path) -> None:
    ensure_private_directory(socket_path.parent)


def validate_private_socket(socket_path: Path) -> None:
    try:
        parent = socket_path.parent.lstat()
        metadata = socket_path.lstat()
    except OSError as exc:
        raise StorageError("executor connector is unavailable") from exc
    user_id = getattr(os, "getuid", lambda: metadata.st_uid)()
    if (
        stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != user_id
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise StorageError("executor connector parent is not private")
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != user_id
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise StorageError("executor connector is not a private user socket")


def write_private_json(path: Path, value: object) -> None:
    ensure_private_directory(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)
