"""Saved MCP credentials are opt-in, scoped, durable and removable."""

import asyncio
from collections.abc import Callable
import json
import os
from pathlib import Path
from typing import cast

import flet as ft
import pytest

import app as app_module
from oauth_client import BrowserOAuthClient
from saved_connections import (
    SavedConnectionStore, StorageAreas, connection_id,
)
from tests.test_connected_ui import StubMcpSession
from tests.ui_helpers import FakePage, find_control


def _storage(tmp_path: Path) -> SavedConnectionStore:
    return SavedConnectionStore(StorageAreas(
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        temp=tmp_path / "temp",
    ))


def test_storage_reads_env_paths_without_writing_or_touching_user_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    for name, suffix in (("DATA", "data"), ("CACHE", "cache"), ("TEMP", "temp")):
        monkeypatch.setenv(f"FLET_APP_STORAGE_{name}", str(tmp_path / suffix))
    areas = StorageAreas.from_flet_environment()
    assert areas == StorageAreas(
        tmp_path / "data", tmp_path / "cache", tmp_path / "temp",
    )
    store = SavedConnectionStore(areas)
    assert store.available
    assert store.list() == []
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "temp").exists()


def test_save_reconnect_delete_and_private_permissions(tmp_path: Path) -> None:
    store = _storage(tmp_path)
    url = "https://example.net/mcp"
    other_url = "https://another.example/mcp"
    first = store.save(url, oauth=False, bearer="sensitive-secret")
    again = store.save(url, oauth=False, bearer="rotated-token")
    other = store.save(other_url, oauth=False, bearer="")
    oauth = store.save(url, oauth=True)
    assert first.identifier == again.identifier
    assert len(store.list()) == 3
    assert store.list()[0].bearer == "rotated-token"
    assert store.list()[1] == other
    assert store.list()[2] == oauth
    assert oauth.auth_label == "Browser OAuth"
    assert again.auth_label == "Bearer token"
    assert other.auth_label == "No authentication"

    profile_path = tmp_path / "data" / "saved-mcp-connections.json"
    assert profile_path.exists()
    if os.name == "posix":
        assert profile_path.stat().st_mode & 0o777 == 0o600
    assert "sensitive-secret" not in profile_path.read_text()
    store.delete(other)
    assert len(store.list()) == 2
    assert store.list()[0].bearer == "rotated-token"
    store.delete(first)
    assert store.list() == [oauth]
    store.delete(oauth)
    assert store.list() == []


def test_cache_and_temp_do_not_contain_credentials(tmp_path: Path) -> None:
    store = _storage(tmp_path)
    url = "https://host.example/mcp?private_key=key-in-url"
    store.save(url, oauth=False, bearer="secrets-are-sensitive")
    store.remember_discovery(url, tools=30, prompts=3, resources=9)
    cache_file = tmp_path / "cache" / "mcp-discovery-counts.json"
    assert cache_file.is_file()
    info = json.loads(cache_file.read_text())
    assert info["tools"] == 30
    assert info["prompts"] == 3
    assert info["resources"] == 9
    assert "key-in-url" not in cache_file.read_text()
    assert "secrets-are-sensitive" not in cache_file.read_text()
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.parametrize("bad", [
    "garbage", "[]", "null", '{"version": 42, "connections": []}',
    '{"version": 1, "connections": [false, {"url": "file:///secret", "oauth": false, "bearer": "a"}]}',
])
def test_corrupt_profiles_are_ignored_without_crash(tmp_path: Path, bad: str) -> None:
    store = _storage(tmp_path)
    file = tmp_path / "data" / "saved-mcp-connections.json"
    file.parent.mkdir()
    file.write_text(bad)
    assert store.list() == []


def test_nothing_is_saved_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    async def run() -> None:
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("FLET_APP_STORAGE_CACHE", str(tmp_path / "cache"))
        monkeypatch.setenv("FLET_APP_STORAGE_TEMP", str(tmp_path / "temp"))
        monkeypatch.setattr(app_module, "McpSession", StubMcpSession)
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        button = cast(ft.FilledTonalButton, find_control(page, "save-connection"))
        assert button.disabled
        assert (tmp_path / "data" / "saved-mcp-connections.json").exists() is False
        endpoint = cast(ft.TextField, find_control(page, "endpoint"))
        endpoint.value = "https://example.net/mcp"
        token = cast(ft.TextField, find_control(page, "bearer-token"))
        token.value = "never-auto-save"
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        connect = cast(ft.FilledTonalButton, actions.controls[0])
        assert connect.on_click is not None
        cast(Callable[[], None], connect.on_click)()
        await asyncio.gather(*page.tasks)
        assert not button.disabled
        assert (tmp_path / "data" / "saved-mcp-connections.json").exists() is False
        assert button.bgcolor is not None
        assert len(StubMcpSession.instances[-1].tool_calls) == 0

    asyncio.run(run())


def test_gui_saved_profile_reconnect_and_remove(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    async def run() -> None:
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("FLET_APP_STORAGE_CACHE", str(tmp_path / "cache"))
        monkeypatch.setenv("FLET_APP_STORAGE_TEMP", str(tmp_path / "temp"))
        monkeypatch.setattr(app_module, "McpSession", StubMcpSession)
        StubMcpSession.instances.clear()
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        endpoint = cast(ft.TextField, find_control(page, "endpoint"))
        endpoint.value = "https://example.net/mcp"
        token = cast(ft.TextField, find_control(page, "bearer-token"))
        token.value = "token-private"
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        connect = cast(ft.FilledTonalButton, actions.controls[0])
        assert connect.on_click is not None
        cast(Callable[[], None], connect.on_click)()
        await asyncio.gather(*page.tasks)
        button = cast(ft.FilledTonalButton, find_control(page, "save-connection"))
        assert button.on_click is not None and not button.disabled
        cast(Callable[[], None], button.on_click)()
        await asyncio.gather(*page.tasks)

        store = _storage(tmp_path)
        profile = store.list()[0]
        assert profile.bearer == "token-private"
        assert profile.url == endpoint.value
        assert "token-private" not in str(find_control(page, "saved-connections"))

        # Disconnect, clear fields and reload without retyping.
        disconnect = cast(ft.OutlinedButton, actions.controls[1])
        assert disconnect.on_click is not None
        cast(Callable[[], None], disconnect.on_click)()
        await asyncio.gather(*page.tasks)
        assert button.disabled
        endpoint.value = ""
        token.value = ""
        reuse = cast(ft.OutlinedButton, find_control(
            page, f"saved-use-{profile.identifier}",
        ))
        assert reuse.on_click is not None
        cast(Callable[[object], None], reuse.on_click)(None)
        await asyncio.gather(*page.tasks)
        assert endpoint.value == "https://example.net/mcp"
        assert token.value == "token-private"
        assert StubMcpSession.instances[-1].bearer == "token-private"
        assert not button.disabled

        # Removing while connected must disconnect and erase the stored token.
        forget = cast(ft.IconButton, find_control(
            page, f"saved-remove-{profile.identifier}",
        ))
        assert forget.on_click is not None
        cast(Callable[[object], None], forget.on_click)(None)
        await asyncio.gather(*page.tasks)
        assert store.list() == []
        assert button.disabled
        assert StubMcpSession.instances[-1].closed

    asyncio.run(run())


def test_saved_profiles_reappear_after_restart_but_never_auto_connect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(app_module, "McpSession", StubMcpSession)
    store = _storage(tmp_path)
    profile = store.save("https://persisted.example/mcp", oauth=False, bearer="again")
    page = FakePage()
    StubMcpSession.instances.clear()
    app_module.main(cast(ft.Page, page))
    assert find_control(page, f"saved-use-{profile.identifier}")
    assert StubMcpSession.instances == []
    assert cast(ft.FilledTonalButton, find_control(page, "save-connection")).disabled


def test_missing_app_data_explains_failed_save_without_creating_fallback_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    assert SavedConnectionStore(StorageAreas.from_flet_environment()).list() == []
    with pytest.raises(OSError, match="not available"):
        SavedConnectionStore(StorageAreas.from_flet_environment()).save(
            "https://example.net/mcp", oauth=False,
        )


def test_oauth_connection_id_is_path_safe() -> None:
    url = "https://example.org/path/../mcp?q=secret"
    identifier = connection_id(url, True)
    assert len(identifier) == 64
    assert all(c in "0123456789abcdef" for c in identifier)



def test_oauth_tokens_and_client_registration_round_trip_through_data_storage(
    tmp_path: Path,
) -> None:
    """Use FastMCP's real adapter; saved OAuth must include refresh + client info."""
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    async def run() -> None:
        store = _storage(tmp_path)
        url = "https://oauth.example/mcp"
        directory = store.oauth_directory(url)
        active = BrowserOAuthClient(url)
        adapter = TokenStorageAdapter(async_key_value=active._store, server_url=url)
        await adapter.set_tokens(OAuthToken(
            access_token="access-private", refresh_token="refresh-private",
            expires_in=3600,
        ))
        await adapter.set_client_info(OAuthClientInformationFull(
            client_id="registered-app", client_secret="client-secret-private",
        ))
        assert not directory.exists()  # In memory until clicking Save.
        await active.persist_credentials(directory)
        assert directory.is_dir()
        assert directory.stat().st_mode & 0o777 == 0o700
        profile = store.save(url, oauth=True)
        assert store.has_oauth_credentials(url)
        assert profile.bearer == ""

        reopened = BrowserOAuthClient(url, stored_tokens=directory)
        next_adapter = TokenStorageAdapter(
            async_key_value=reopened._store, server_url=url,
        )
        tokens = await next_adapter.get_tokens()
        assert tokens is not None
        assert tokens.access_token == "access-private"
        assert tokens.refresh_token == "refresh-private"
        client = await next_adapter.get_client_info()
        assert client is not None
        assert client.client_id == "registered-app"
        assert client.client_secret == "client-secret-private"
        assert await next_adapter.get_token_expiry() is not None

        await reopened.close()
        await active.close()
        store.delete(profile)
        assert store.list() == []
        assert not directory.exists()
        assert not store.has_oauth_credentials(url)

    asyncio.run(run())


def test_oauth_refresh_after_save_is_persisted_on_disconnect(tmp_path: Path) -> None:
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthToken

    async def run() -> None:
        store = _storage(tmp_path)
        url = "https://oauth.example/mcp"
        directory = store.oauth_directory(url)
        active = BrowserOAuthClient(url)
        adapter = TokenStorageAdapter(async_key_value=active._store, server_url=url)
        await adapter.set_tokens(OAuthToken(access_token="first", expires_in=600))
        await active.persist_credentials(directory)
        store.save(url, oauth=True)
        await adapter.set_tokens(OAuthToken(access_token="refreshed", expires_in=600))
        await active.close()
        reopened = BrowserOAuthClient(url, stored_tokens=directory)
        persisted = TokenStorageAdapter(async_key_value=reopened._store, server_url=url)
        tokens = await persisted.get_tokens()
        assert tokens is not None and tokens.access_token == "refreshed"
        await reopened.close()

    asyncio.run(run())


def test_oauth_unsaved_login_never_writes_persistent_credentials(tmp_path: Path) -> None:
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthToken

    async def run() -> None:
        store = _storage(tmp_path)
        client = BrowserOAuthClient("https://oauth.example/mcp")
        adapter = TokenStorageAdapter(
            async_key_value=client._store, server_url=client.url,
        )
        await adapter.set_tokens(OAuthToken(access_token="not-to-save"))
        await client.close()
        assert not store.oauth_directory(client.url).exists()
        assert store.list() == []

    asyncio.run(run())



def test_oauth_token_refresh_mirrors_immediately_without_disconnect(tmp_path: Path) -> None:
    """Rotating refresh tokens must be durable even if the app crashes later."""
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthToken

    async def run() -> None:
        url = "https://oauth.example/mcp"
        store = _storage(tmp_path)
        directory = store.oauth_directory(url)
        active = BrowserOAuthClient(url)
        adapter = TokenStorageAdapter(async_key_value=active._store, server_url=url)
        await adapter.set_tokens(OAuthToken(
            access_token="before", refresh_token="refresh-before",
        ))
        await active.persist_credentials(directory)
        await adapter.set_tokens(OAuthToken(
            access_token="after", refresh_token="refresh-after",
        ))

        # Read directly from disk without calling close() on the active client.
        saved = BrowserOAuthClient(url, stored_tokens=directory)
        on_disk = TokenStorageAdapter(async_key_value=saved._store, server_url=url)
        tokens = await on_disk.get_tokens()
        assert tokens is not None
        assert tokens.access_token == "after"
        assert tokens.refresh_token == "refresh-after"
        await saved.close()
        await active.close()

    asyncio.run(run())


def test_oauth_stop_persisting_does_not_recreate_deleted_tokens(
    tmp_path: Path,
) -> None:
    from fastmcp.client.auth.oauth import TokenStorageAdapter
    from mcp.shared.auth import OAuthToken

    async def run() -> None:
        url = "https://oauth.example/mcp"
        store = _storage(tmp_path)
        directory = store.oauth_directory(url)
        active = BrowserOAuthClient(url)
        adapter = TokenStorageAdapter(async_key_value=active._store, server_url=url)
        await adapter.set_tokens(OAuthToken(access_token="secret"))
        await active.persist_credentials(directory)
        profile = store.save(url, oauth=True)
        active.stop_persisting()
        store.delete(profile)
        assert not directory.exists()
        await adapter.set_tokens(OAuthToken(access_token="should-not-be-saved"))
        await active.close()
        assert not directory.exists()

    asyncio.run(run())


def test_saved_oauth_profile_reconnect_and_delete_via_gui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class OAuthSessionStub(StubMcpSession):
        def __init__(
            self, url: str, bearer: str, *, oauth: bool = False,
            oauth_store_path: Path | None = None,
        ) -> None:
            super().__init__(url, bearer, oauth=oauth)
            self.loaded_store = oauth_store_path
            self.stopped = False

        def stop_oauth_persistence(self) -> None:
            self.stopped = True

    async def run() -> None:
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
        monkeypatch.setattr(app_module, "McpSession", OAuthSessionStub)
        StubMcpSession.instances.clear()
        store = _storage(tmp_path)
        url = "https://oauth.example/mcp"
        directory = store.oauth_directory(url)
        client = BrowserOAuthClient(url)
        from fastmcp.client.auth.oauth import TokenStorageAdapter
        from mcp.shared.auth import OAuthToken
        adapter = TokenStorageAdapter(async_key_value=client._store, server_url=url)
        await adapter.set_tokens(OAuthToken(access_token="oauth-secret"))
        await client.persist_credentials(directory)
        await client.close()
        profile = store.save(url, oauth=True)

        page = FakePage()
        app_module.main(cast(ft.Page, page))
        save = cast(ft.FilledTonalButton, find_control(page, "save-connection"))
        assert save.disabled
        button = cast(ft.OutlinedButton, find_control(
            page, f"saved-use-{profile.identifier}",
        ))
        assert button.on_click is not None
        cast(Callable[[object], None], button.on_click)(None)
        await asyncio.gather(*page.tasks)
        active = StubMcpSession.instances[-1]
        assert isinstance(active, OAuthSessionStub)
        assert active.oauth
        assert active.loaded_store == directory
        assert not save.disabled

        forget = cast(ft.IconButton, find_control(
            page, f"saved-remove-{profile.identifier}",
        ))
        assert forget.on_click is not None
        cast(Callable[[object], None], forget.on_click)(None)
        await asyncio.gather(*page.tasks)
        assert active.stopped
        assert active.closed
        assert save.disabled
        assert store.list() == []
        assert not directory.exists()

    asyncio.run(run())


def test_saved_connection_rows_do_not_rebuild_when_status_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    async def run() -> None:
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
        monkeypatch.setattr(app_module, "McpSession", StubMcpSession)
        store = _storage(tmp_path)
        profile = store.save("https://same.example/mcp", oauth=False)
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        original = find_control(page, f"saved-use-{profile.identifier}")
        assert isinstance(original, ft.OutlinedButton)
        assert not original.disabled

        endpoint = cast(ft.TextField, find_control(page, "endpoint"))
        endpoint.value = profile.url
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        connect = cast(ft.FilledTonalButton, actions.controls[0])
        assert connect.on_click is not None
        cast(Callable[[], None], connect.on_click)()
        await asyncio.gather(*page.tasks)
        assert find_control(page, f"saved-use-{profile.identifier}") is original
        assert original.disabled
        disconnect = cast(ft.OutlinedButton, actions.controls[1])
        assert disconnect.on_click is not None
        cast(Callable[[], None], disconnect.on_click)()
        await asyncio.gather(*page.tasks)
        assert find_control(page, f"saved-use-{profile.identifier}") is original
        assert not original.disabled

    asyncio.run(run())



def test_connect_initialization_failure_keeps_ui_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnusableMcpSession:
        def __init__(self, url: str, bearer: str, *, oauth: bool = False) -> None:
            raise PermissionError("Stored credentials directory is inaccessible")

    async def run() -> None:
        monkeypatch.setattr(app_module, "McpSession", UnusableMcpSession)
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        endpoint = cast(ft.TextField, find_control(page, "endpoint"))
        endpoint.value = "https://example.net/mcp"
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        connect = cast(ft.FilledTonalButton, actions.controls[0])
        assert connect.on_click is not None
        cast(Callable[[], None], connect.on_click)()
        await asyncio.gather(*page.tasks)
        assert not connect.disabled
        assert cast(ft.FilledTonalButton, find_control(page, "save-connection")).disabled
        connection_card = cast(ft.Container, find_control(page, "connection-card"))
        status = cast(ft.Text, cast(ft.Column, connection_card.content).controls[-1])
        assert "Connection failed: PermissionError" in status.value

    asyncio.run(run())


def test_failed_oauth_profile_save_discards_secret_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class SavingOAuthSession(StubMcpSession):
        stopped = False

        async def save_oauth_credentials(self, directory: Path) -> None:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "secret").write_text("oauth-secret", encoding="utf-8")

        def stop_oauth_persistence(self) -> None:
            self.stopped = True

    def denied(self: SavedConnectionStore, url: str, *, oauth: bool, bearer: str = "") -> object:
        raise PermissionError("Cannot write profile index")

    async def run() -> None:
        monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path / "data"))
        monkeypatch.setattr(app_module, "McpSession", SavingOAuthSession)
        monkeypatch.setattr(SavedConnectionStore, "save", denied)
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        endpoint = cast(ft.TextField, find_control(page, "endpoint"))
        endpoint.value = "https://oauth.example/mcp"
        browser = cast(ft.Checkbox, find_control(page, "browser-oauth"))
        browser.value = True
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        connect = cast(ft.FilledTonalButton, actions.controls[0])
        assert connect.on_click is not None
        cast(Callable[[], None], connect.on_click)()
        await asyncio.gather(*page.tasks)
        save = cast(ft.FilledTonalButton, find_control(page, "save-connection"))
        assert not save.disabled and save.on_click is not None
        cast(Callable[[], None], save.on_click)()
        await asyncio.gather(*page.tasks)
        assert not (tmp_path / "data" / "mcp-oauth-tokens").joinpath(
            connection_id(endpoint.value or "", True),
        ).exists()
        active = StubMcpSession.instances[-1]
        assert isinstance(active, SavingOAuthSession) and active.stopped
        assert "Save failed" in cast(ft.Text, find_control(page, "save-connection-notice")).value
        assert not (tmp_path / "data" / "saved-mcp-connections.json").exists()

    asyncio.run(run())


def test_deletion_reports_directory_error_and_preserves_profile_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import saved_connections

    store = _storage(tmp_path)
    profile = store.save("https://oauth.example/mcp", oauth=True)
    directory = store.oauth_directory(profile.url)
    directory.mkdir(parents=True)
    (directory / "fake-credential").write_text("private")
    def cannot_delete(path: Path) -> None:
        raise PermissionError("No permission to delete OAuth credentials")

    monkeypatch.setattr(saved_connections.shutil, "rmtree", cannot_delete)
    with pytest.raises(PermissionError, match="No permission"):
        store.delete(profile)
    assert store.list() == [profile]
    assert directory.exists()
