from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PolicyError(ValueError):
    """Raised when a local browser file policy is absent or exceeded."""


def _config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "llm-wiki" / "browser-executor.json"


def _roots(value: Any, name: str) -> tuple[Path, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise PolicyError(f"{name} must be a bounded array")
    roots: list[Path] = []
    for item in value:
        if not isinstance(item, str) or not item.startswith("/"):
            raise PolicyError(f"{name} entries must be absolute paths")
        path = Path(item).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise PolicyError(f"{name} entries must be directories")
        roots.append(path)
    return tuple(roots)


@dataclass(frozen=True)
class LocalBrowserPolicy:
    upload_roots: tuple[Path, ...] = ()
    download_roots: tuple[Path, ...] = ()

    @classmethod
    def load(cls, path: Path | None = None) -> "LocalBrowserPolicy":
        source = path or _config_path()
        if not source.exists():
            return cls()
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError("browser file policy is unreadable") from exc
        if not isinstance(value, dict) or set(value).difference(
            {"upload_roots", "download_roots"}
        ):
            raise PolicyError("browser file policy contains unsupported fields")
        return cls(
            upload_roots=_roots(value.get("upload_roots", []), "upload_roots"),
            download_roots=_roots(value.get("download_roots", []), "download_roots"),
        )

    @staticmethod
    def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
        return any(path == root or root in path.parents for root in roots)

    def validate_uploads(self, values: Any) -> list[Path]:
        if not isinstance(values, list) or not 1 <= len(values) <= 16:
            raise PolicyError("uploads must contain one to sixteen paths")
        if not self.upload_roots:
            raise PolicyError(
                "no upload roots are registered in the local browser policy"
            )
        result: list[Path] = []
        for value in values:
            if not isinstance(value, str) or not value.startswith("/"):
                raise PolicyError("upload paths must be absolute")
            source = Path(value)
            if source.is_symlink():
                raise PolicyError("an upload path is outside the registered roots")
            path = source.resolve(strict=True)
            if not path.is_file() or not self._inside(path, self.upload_roots):
                raise PolicyError("an upload path is outside the registered roots")
            result.append(path)
        return result

    def validate_download(self, value: Any) -> Path:
        if (
            not isinstance(value, str)
            or not value.startswith("/")
            or not self.download_roots
        ):
            raise PolicyError("download path is outside the registered roots")
        source = Path(value)
        if source.is_symlink():
            raise PolicyError("download path is outside the registered roots")
        path = source.resolve(strict=True)
        if not path.is_file() or not self._inside(path, self.download_roots):
            raise PolicyError("download path is outside the registered roots")
        return path
