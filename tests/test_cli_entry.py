# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

from src import cli


def _ns(**overrides):
    defaults = {
        "subcommand": None,
        "interactive": False,
        "sync": False,
        "backup": False,
        "export": None,
        "status": False,
        "watch": None,
        "quiet": False,
        "verbose": False,
        "no_color": False,
        "dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class _DummyParser:
    def __init__(self, args: argparse.Namespace):
        self._args = args
        self.help_called = False

    def parse_args(self) -> argparse.Namespace:
        return self._args

    def print_help(self) -> None:
        self.help_called = True


class TestMainEntryBehavior:
    def test_main_prints_help_and_exits_0_when_no_action(self, monkeypatch):
        parser = _DummyParser(_ns())
        monkeypatch.setattr(cli, "_build_parser", lambda: parser)

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0
        assert parser.help_called is True

    def test_main_rejects_quiet_plus_verbose(self, monkeypatch):
        parser = _DummyParser(_ns(quiet=True, verbose=True))
        monkeypatch.setattr(cli, "_build_parser", lambda: parser)

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 2

    def test_main_exits_1_when_config_load_fails(self, monkeypatch):
        parser = _DummyParser(_ns(sync=True))
        monkeypatch.setattr(cli, "_build_parser", lambda: parser)

        path_calls = []
        log_calls = []

        monkeypatch.setattr(cli, "_setup_paths", lambda _args: path_calls.append(True))
        monkeypatch.setattr(cli, "_setup_logging", lambda _args: log_calls.append(True))

        import src.models.app_config as app_config_module

        monkeypatch.setattr(
            app_config_module.AppConfig, "load", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("boom")))
        )

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 1
        assert path_calls == [True]
        assert log_calls == [True]

    def test_main_calls_dispatch_and_exits_with_dispatch_code(self, monkeypatch):
        parser = _DummyParser(_ns(sync=True, no_color=True))
        monkeypatch.setattr(cli, "_build_parser", lambda: parser)

        path_calls = []
        log_calls = []
        dispatch_calls = []

        monkeypatch.setattr(cli, "_setup_paths", lambda _args: path_calls.append(True))
        monkeypatch.setattr(cli, "_setup_logging", lambda _args: log_calls.append(True))

        fake_config = SimpleNamespace()

        import src.models.app_config as app_config_module

        monkeypatch.setattr(app_config_module.AppConfig, "load", classmethod(lambda cls: fake_config))

        monkeypatch.setattr(
            cli, "_dispatch", lambda config, args, parser_obj: dispatch_calls.append((config, args, parser_obj)) or 7
        )

        cli._NO_COLOR = None

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 7
        assert cli._NO_COLOR is True
        assert path_calls == [True]
        assert log_calls == [True]
        assert len(dispatch_calls) == 1
        assert dispatch_calls[0][0] is fake_config
        assert dispatch_calls[0][1] is parser._args
        assert dispatch_calls[0][2] is parser


class TestDispatchWithRealParser:
    def test_dispatch_routes_config_get_subcommand(self, monkeypatch):
        parser = cli._build_parser()
        args = parser.parse_args(["config", "get", "webdav.url"])

        called = []
        monkeypatch.setattr(cli, "_cmd_config_get", lambda config, a: called.append((config, a.key)) or 0)

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert rc == 0
        assert len(called) == 1
        assert called[0][1] == "webdav.url"

    def test_dispatch_routes_db_stats_to_status(self, monkeypatch):
        parser = cli._build_parser()
        args = parser.parse_args(["db", "stats", "--json"])

        called = []
        monkeypatch.setattr(cli, "_cmd_status", lambda config, a: called.append(a.json) or 0)

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert rc == 0
        assert called == [True]

    def test_dispatch_prioritizes_watch_when_sync_and_watch_set(self, monkeypatch):
        parser = cli._build_parser()
        args = parser.parse_args(["-s", "-w", "5"])

        called = []
        monkeypatch.setattr(cli, "_cmd_watch", lambda config, a: called.append("watch") or 0)
        monkeypatch.setattr(cli, "_cmd_sync", lambda config, a: called.append("sync") or 0)

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert rc == 0
        assert called == ["watch"]

    def test_dispatch_runs_classic_actions_in_order(self, monkeypatch):
        parser = cli._build_parser()
        args = parser.parse_args(["-s", "-b", "-e", "out.csv"])

        calls = []
        monkeypatch.setattr(cli, "_cmd_sync", lambda config, a: calls.append("sync") or 0)
        monkeypatch.setattr(cli, "_cmd_backup", lambda config, a: calls.append("backup") or 2)
        monkeypatch.setattr(cli, "_cmd_export", lambda config, a: calls.append("export") or 0)

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert calls == ["sync", "backup", "export"]
        assert rc == 2

    def test_dispatch_uses_latest_nonzero_exit_code_from_classic_actions(self, monkeypatch):
        parser = cli._build_parser()
        args = parser.parse_args(["-s", "-b", "-e", "out.csv"])

        monkeypatch.setattr(cli, "_cmd_sync", lambda config, a: 1)
        monkeypatch.setattr(cli, "_cmd_backup", lambda config, a: 2)
        monkeypatch.setattr(cli, "_cmd_export", lambda config, a: 3)

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert rc == 3

    def test_dispatch_prints_help_when_no_action(self):
        parser = cli._build_parser()
        args = parser.parse_args([])

        rc = cli._dispatch(SimpleNamespace(), args, parser)

        assert rc == 0
