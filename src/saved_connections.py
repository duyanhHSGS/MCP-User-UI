"""Opt-in MCP endpoint profiles in Flet app-private storage.

DATA is durable; CACHE contains only disposable counts; TEMP contains only
scratch of those counts. No bearer or OAuth credentials enter CACHE or TEMP.
This is local private storage, NOT encrypted OS secure storage.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from transport import validate_endpoint

_PROFILE_FILENAME = "saved-mcp-connections.json"
_MAX_PROFILES = 64


@dataclass(frozen=True)
class StorageAreas:
    data: Path | None
    cache: Path | None
    temp: Path | None

    @classmethod
    def from_flet_environment(cls) -> StorageAreas:
        def directory(name: str) -> Path | None:
            value = os.environ.get(name)
            return Path(value) if value else None

        return cls(
            directory("FLET_APP_STORAGE_DATA"),
            directory("FLET_APP_STORAGE_CACHE"),
            directory("FLET_APP_STORAGE_TEMP"),
        )


@dataclass(frozen=True)
class SavedConnection:
    identifier: str
    url: str
    oauth: bool
    bearer: str

    @property
    def auth_label(self) -> str:
        if self.oauth:
            return "Browser OAuth"
        if self.bearer:
            return "Bearer token"
        return "No authentication"


def connection_id(url: str, oauth: bool) -> str:
    """Deterministic, safe file/directory key without leaking secret URLs."""
    canonical = validate_endpoint(url)
    return hashlib.sha256(f"{canonical}\0{int(oauth)}".encode()).hexdigest()


def _private_write(file: Path, content: bytes) -> None:
    """Write sensitive data atomically at 0600, never via CACHE/TEMP."""
    file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".profile-", dir=file.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            # fchmod is POSIX-only; Windows app-private directories use ACLs.
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            else:
                os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SavedConnectionStore:
    def __init__(self, areas: StorageAreas) -> None:
        self.areas = areas

    @property
    def available(self) -> bool:
        return self.areas.data is not None

    @property
    def _profile_path(self) -> Path:
        if self.areas.data is None:
            raise OSError("Flet app data storage is not available in this runtime.")
        return self.areas.data / _PROFILE_FILENAME

    def list(self) -> list[SavedConnection]:
        try:
            raw = json.loads(self._profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return []
        entries = raw.get("connections")
        if not isinstance(entries, list):
            return []
        results: list[SavedConnection] = []
        for entry in entries[:_MAX_PROFILES]:
            if not isinstance(entry, dict):
                continue
            url, oauth, bearer = (
                entry.get("url"), entry.get("oauth"), entry.get("bearer"),
            )
            if not isinstance(url, str) or not isinstance(oauth, bool) or not isinstance(bearer, str):
                continue
            try:
                identifier = connection_id(url, oauth)
            except ValueError:
                continue
            if len(bearer) > 100_000:
                continue
            results.append(SavedConnection(identifier, url, oauth, bearer if not oauth else ""))
        return results

    def oauth_directory(self, url: str) -> Path:
        if self.areas.data is None:
            raise OSError("Flet app data storage is not available in this runtime.")
        return self.areas.data / "mcp-oauth-tokens" / connection_id(url, True)

    def has_oauth_credentials(self, url: str) -> bool:
        """Only saved OAuth profiles may cause on-disk token storage to open."""
        identifier = connection_id(url, True)
        return any(
            profile.identifier == identifier and profile.oauth for profile in self.list()
        ) and self.oauth_directory(url).is_dir()

    def discard_oauth_credentials(self, url: str) -> None:
        """Remove only this endpoint's secret subtree, even after a failed save."""
        directory = self.oauth_directory(url)
        if directory.exists():
            shutil.rmtree(directory)

    def save(self, url: str, *, oauth: bool, bearer: str = "") -> SavedConnection:
        canonical = validate_endpoint(url)
        if len(canonical) > 4096 or len(bearer) > 100_000:
            raise ValueError("Connection URL or token exceeds the storage size limit.")
        saved = SavedConnection(
            connection_id(canonical, oauth), canonical, oauth,
            "" if oauth else bearer,
        )
        profiles = [entry for entry in self.list() if entry.identifier != saved.identifier]
        if len(profiles) >= _MAX_PROFILES:
            raise ValueError(f"Saved connection limit reached ({_MAX_PROFILES}).")
        profiles.append(saved)
        payload = {
            "version": 1,
            "connections": [
                {"url": entry.url, "oauth": entry.oauth, "bearer": entry.bearer}
                for entry in profiles
            ],
        }
        _private_write(
            self._profile_path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return saved

    def delete(self, profile: SavedConnection) -> None:
        """Delete only the explicitly selected entry and its own OAuth cache."""
        profiles = [entry for entry in self.list() if entry.identifier != profile.identifier]
        payload = {
            "version": 1,
            "connections": [
                {"url": entry.url, "oauth": entry.oauth, "bearer": entry.bearer}
                for entry in profiles
            ],
        }
        if profile.oauth:
            # Delete credentials first and propagate failures instead of claiming
            # successful removal while secrets are still left on disk.
            self.discard_oauth_credentials(profile.url)
        _private_write(
            self._profile_path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def remember_discovery(
        self, url: str, *, tools: int, prompts: int, resources: int,
    ) -> None:
        """Cache *only counts*; no URL, tool arguments, tokens, or response body."""
        if self.areas.cache is None or self.areas.temp is None:
            return
        snapshot = {
            "connection_id": connection_id(url, False)[:16],
            "tools": tools,
            "prompts": prompts,
            "resources": resources,
            "recorded_at": time.time(),
        }
        stage: str | None = None
        try:
            self.areas.temp.mkdir(parents=True, exist_ok=True)
            self.areas.cache.mkdir(parents=True, exist_ok=True)
            descriptor, stage = tempfile.mkstemp(prefix="mcp-counts-", dir=self.areas.temp)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(snapshot, file)
            destination = self.areas.cache / "mcp-discovery-counts.json"
            _private_write(destination, Path(stage).read_bytes())
        except OSError:
            pass  # Cache failures must never break a successful MCP connection.
        finally:
            if stage is not None:
                Path(stage).unlink(missing_ok=True)
