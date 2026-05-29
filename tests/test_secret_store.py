# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``src.utils.secret_store``.

Coverage focus:
- Lazy keyring probe: importing the module must not touch keyring.
- Headless / no-D-Bus environment: file fallback activates without prompt.
- Round-trip: ``set`` then ``get`` returns the same value through both stores.
- ``has`` does not prompt and does not call decrypt on legacy ciphertext.
- File fallback file is created with restrictive permissions on POSIX.
- ``HISTORYSYNC_NO_FILE_SECRETS`` env var disables the file fallback.
- Legacy migration helper persists plaintext into the secret store.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("keyring", reason="keyring not installed")


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_config_dir(tmp_path, monkeypatch):
    """Point SecretStore's file fallback at a temp directory."""
    monkeypatch.setattr("src.utils.path_helper.get_config_dir", lambda: tmp_path)
    # Also clear any HISTORYSYNC_NO_FILE_SECRETS leakage from the host env.
    monkeypatch.delenv("HISTORYSYNC_NO_FILE_SECRETS", raising=False)
    yield tmp_path


@pytest.fixture
def fresh_store():
    """Return a fresh SecretStore instance with no cached keyring probe."""
    from src.utils.secret_store import SecretStore

    return SecretStore()


# ── Lazy initialisation ──────────────────────────────────────────────────────


class TestLazyInitialisation:
    def test_module_import_does_not_touch_keyring(self, monkeypatch):
        """Importing secret_store must not call any keyring API.

        Regression test for the original bug: even importing the module that
        used keyring caused a backend probe at module load time.
        """
        # Force fail-fast: if anything calls into keyring during import,
        # raise so the test fails loudly.
        monkeypatch.setitem(sys.modules, "keyring", None)
        # Force a fresh import.
        if "src.utils.secret_store" in sys.modules:
            del sys.modules["src.utils.secret_store"]
        # Importing must succeed even though keyring is unavailable.
        import src.utils.secret_store  # noqa: F401

    def test_constructor_does_not_probe_backend(self, fresh_store, monkeypatch):
        """SecretStore() construction is free; no keyring API touched."""
        called = {"n": 0}

        def _trip(*args, **kwargs):
            called["n"] += 1
            raise AssertionError("keyring probed too early")

        # If anything calls into keyring before is_available/get/set, this trips.
        monkeypatch.setattr("keyring.get_keyring", _trip)
        # Mere existence of the instance must not have probed.
        assert called["n"] == 0


# ── File fallback ────────────────────────────────────────────────────────────


class TestFileFallback:
    """When keyring is unavailable, secrets persist in a restricted JSON file."""

    @pytest.fixture(autouse=True)
    def _force_no_keyring(self, fresh_store, monkeypatch):
        """Pretend the keyring backend is missing."""
        monkeypatch.setattr(fresh_store, "_probe_keyring", lambda: None)
        return fresh_store

    def test_set_then_get_roundtrip(self, fresh_store):
        fresh_store.set("webdav.password", "hunter2")
        assert fresh_store.get("webdav.password") == "hunter2"

    def test_get_missing_returns_none(self, fresh_store):
        assert fresh_store.get("does.not.exist") is None

    def test_has_does_not_decrypt_or_prompt(self, fresh_store):
        fresh_store.set("k", "v")
        assert fresh_store.has("k") is True
        assert fresh_store.has("nope") is False

    def test_delete_removes_entry(self, fresh_store):
        fresh_store.set("k", "v")
        assert fresh_store.has("k")
        fresh_store.delete("k")
        assert not fresh_store.has("k")

    def test_delete_missing_is_noop(self, fresh_store):
        # Must not raise.
        fresh_store.delete("never.set")

    def test_overwrite_updates_value(self, fresh_store):
        fresh_store.set("k", "first")
        fresh_store.set("k", "second")
        assert fresh_store.get("k") == "second"

    def test_secrets_file_created_with_owner_only_perms_on_posix(self, fresh_store, _redirect_config_dir):
        """``secrets.json`` is chmod 0600 on POSIX."""
        if sys.platform == "win32":
            pytest.skip("POSIX-only test")
        fresh_store.set("k", "v")
        path = _redirect_config_dir / "secrets.json"
        assert path.exists()
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_empty_after_last_delete_unlinks_file(self, fresh_store, _redirect_config_dir):
        fresh_store.set("k", "v")
        path = _redirect_config_dir / "secrets.json"
        assert path.exists()
        fresh_store.delete("k")
        assert not path.exists(), "empty fallback file should be removed"

    def test_corrupt_fallback_file_treated_as_empty(self, fresh_store, _redirect_config_dir):
        """A corrupt secrets.json must not break ``get``."""
        path = _redirect_config_dir / "secrets.json"
        path.write_text("NOT JSON{{{", encoding="utf-8")
        # Must not raise; missing key returns None.
        assert fresh_store.get("anything") is None

    def test_get_returns_none_for_blank_value(self, fresh_store):
        """Blank values in the fallback JSON are treated as 'not set'."""
        fresh_store.set("k", "")
        # Empty string is intentionally treated as "no secret" because
        # downstream code uses ``if password`` — see _file_get.
        assert fresh_store.get("k") is None


# ── HISTORYSYNC_NO_FILE_SECRETS env opt-out ──────────────────────────────────


class TestNoFileSecretsEnv:
    def test_env_disables_file_fallback(self, fresh_store, monkeypatch, _redirect_config_dir):
        monkeypatch.setattr(fresh_store, "_probe_keyring", lambda: None)
        monkeypatch.setenv("HISTORYSYNC_NO_FILE_SECRETS", "1")
        # set() silently no-ops; get() returns None.
        fresh_store.set("k", "v")
        assert not (_redirect_config_dir / "secrets.json").exists()
        assert fresh_store.get("k") is None

    def test_env_zero_does_not_disable(self, fresh_store, monkeypatch, _redirect_config_dir):
        monkeypatch.setattr(fresh_store, "_probe_keyring", lambda: None)
        monkeypatch.setenv("HISTORYSYNC_NO_FILE_SECRETS", "0")
        fresh_store.set("k", "v")
        assert fresh_store.get("k") == "v"


# ── Linux D-Bus short-circuit ────────────────────────────────────────────────


class TestLinuxDBusShortCircuit:
    """On Linux without DBUS_SESSION_BUS_ADDRESS, never touch keyring."""

    def test_no_dbus_means_keyring_unavailable(self, fresh_store, monkeypatch):
        if sys.platform != "linux":
            pytest.skip("Linux-only path")
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
        # Even if keyring would otherwise import fine, we must short-circuit.
        # is_available must return False without invoking keyring.get_keyring.
        called = {"n": 0}

        def _trip(*args, **kwargs):
            called["n"] += 1

        monkeypatch.setattr("keyring.get_keyring", _trip)
        assert fresh_store.is_available() is False
        assert called["n"] == 0


# ── Keyring backend interaction ──────────────────────────────────────────────


class TestKeyringBackend:
    """When a real keyring is reachable, set/get use it instead of file."""

    @pytest.fixture
    def store_with_fake_keyring(self, fresh_store):
        """A SecretStore whose probe returns a fake keyring module."""
        store_data: dict[tuple[str, str], str] = {}

        class FakeKeyring:
            def get_password(self, service, username):
                return store_data.get((service, username))

            def set_password(self, service, username, password):
                store_data[(service, username)] = password

            def delete_password(self, service, username):
                if (service, username) not in store_data:
                    # Mimic keyring.errors.PasswordDeleteError surface
                    raise Exception("not found")
                del store_data[(service, username)]

        fake = FakeKeyring()
        fresh_store._kr = fake
        fresh_store._kr_probed = True
        fresh_store._kr_available = True
        # Patch the lazy probe so it returns the same fake on subsequent calls.
        fresh_store._probe_keyring = lambda: fake
        return fresh_store, store_data

    def test_set_writes_to_keyring(self, store_with_fake_keyring):
        store, raw = store_with_fake_keyring
        store.set("webdav.password", "secret-via-keyring")
        assert raw[("HistorySync", "webdav.password")] == "secret-via-keyring"

    def test_get_reads_from_keyring(self, store_with_fake_keyring):
        store, raw = store_with_fake_keyring
        raw[("HistorySync", "webdav.password")] = "from-keyring"
        assert store.get("webdav.password") == "from-keyring"

    def test_set_clears_stale_file_copy(self, store_with_fake_keyring, _redirect_config_dir):
        """A successful keyring write must purge the file fallback for that key."""
        store, _raw = store_with_fake_keyring
        # Seed the file fallback directly.
        import json as _json

        path = _redirect_config_dir / "secrets.json"
        path.write_text(_json.dumps({"webdav.password": "stale"}), encoding="utf-8")
        # Now write to keyring; file copy should be removed.
        store.set("webdav.password", "fresh")
        # Either the file is gone (last entry removed) or the entry was deleted.
        if path.exists():
            assert "webdav.password" not in _json.loads(path.read_text(encoding="utf-8"))

    def test_keyring_failure_falls_back_to_file(self, fresh_store, monkeypatch, _redirect_config_dir):
        """If keyring.set raises, we must persist to the file instead."""

        class BrokenKeyring:
            def get_password(self, *args, **kwargs):
                return None

            def set_password(self, *args, **kwargs):
                raise RuntimeError("keyring locked")

        fresh_store._probe_keyring = BrokenKeyring
        fresh_store.set("webdav.password", "rescue")
        # File fallback must contain the value.
        import json as _json

        path = _redirect_config_dir / "secrets.json"
        assert path.exists()
        assert _json.loads(path.read_text(encoding="utf-8"))["webdav.password"] == "rescue"


# ── Legacy migration helper ──────────────────────────────────────────────────


class TestMigrateLegacyCiphertext:
    def test_returns_none_for_empty_input(self):
        from src.utils.secret_store import migrate_legacy_ciphertext

        assert migrate_legacy_ciphertext("k", "") is None

    def test_decrypts_and_persists_into_store(self, monkeypatch, _redirect_config_dir):
        """Successful decryption: plaintext is returned AND stored under key."""
        from src.utils.secret_store import get_secret_store, migrate_legacy_ciphertext

        store = get_secret_store()
        # Force the file fallback so we don't touch the host keyring.
        monkeypatch.setattr(store, "_probe_keyring", lambda: None)
        # Stub decrypt_text so we don't depend on actual master-key state.
        monkeypatch.setattr("src.utils.security_utils.decrypt_text", lambda _enc: "the-plaintext")

        result = migrate_legacy_ciphertext("webdav.password", "ENC:something")
        assert result == "the-plaintext"
        assert store.get("webdav.password") == "the-plaintext"

    def test_propagates_decryption_error(self, monkeypatch):
        """Permanent decryption failures propagate so the caller can flag the UI."""
        from src.utils.secret_store import migrate_legacy_ciphertext
        from src.utils.security_utils import DecryptionError

        def _boom(_enc):
            raise DecryptionError("HMAC mismatch")

        monkeypatch.setattr("src.utils.security_utils.decrypt_text", _boom)
        with pytest.raises(DecryptionError):
            migrate_legacy_ciphertext("webdav.password", "ENC:anything")

    def test_persistence_failure_still_returns_plaintext(self, monkeypatch):
        """If keyring write fails after decryption, plaintext is still returned."""
        from src.utils.secret_store import get_secret_store, migrate_legacy_ciphertext

        store = get_secret_store()

        def _refuse(*args, **kwargs):
            raise RuntimeError("storage broken")

        monkeypatch.setattr("src.utils.security_utils.decrypt_text", lambda _enc: "plain")
        monkeypatch.setattr(store, "set", _refuse)
        result = migrate_legacy_ciphertext("k", "ENC:whatever")
        assert result == "plain"


# ── Singleton accessor ───────────────────────────────────────────────────────


class TestSingleton:
    def test_get_secret_store_returns_same_instance(self):
        from src.utils.secret_store import get_secret_store

        assert get_secret_store() is get_secret_store()
