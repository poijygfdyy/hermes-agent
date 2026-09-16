"""Fairness regressions for the gateway's bounded kanban auto-decompose sweep."""

from __future__ import annotations

import contextlib
import os
import sys
from types import SimpleNamespace

import hermes_cli

from gateway import kanban_watchers_dispatcher as kwd


def _dispatcher():
    settings = kwd._DispatcherSettings(60.0, None, None, 2, 0, True, None, None)
    return kwd._KanbanDispatcher(SimpleNamespace(DEFAULT_BOARD="default"), settings)


def _install_fake_decomposer(monkeypatch, board_tasks, attempts, successful=frozenset()):
    def list_triage_ids():
        board = os.environ["HERMES_KANBAN_BOARD"]
        return list(board_tasks.get(board, ()))

    def decompose_task(task_id, author=None):
        board = os.environ["HERMES_KANBAN_BOARD"]
        attempts.append((board, task_id))
        ok = (board, task_id) in successful
        if ok:
            board_tasks[board].remove(task_id)
        return SimpleNamespace(
            ok=ok,
            fanout=False,
            child_ids=None,
            reason=None if ok else "synthetic failure",
        )

    fake = SimpleNamespace(
        list_triage_ids=list_triage_ids,
        decompose_task=decompose_task,
    )
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_decompose", fake)
    monkeypatch.setattr(hermes_cli, "kanban_decompose", fake, raising=False)
    monkeypatch.setattr(
        kwd,
        "_default_profile_secret_scope",
        lambda: contextlib.nullcontext(),
    )
    monkeypatch.setattr(kwd, "_board_slugs", lambda kb: list(board_tasks))


def test_failed_prefix_does_not_starve_later_tasks_or_boards(monkeypatch):
    board_tasks = {
        "alpha": ["a1", "a2", "a3", "a4"],
        "beta": ["b1"],
    }
    attempts = []
    _install_fake_decomposer(
        monkeypatch,
        board_tasks,
        attempts,
        successful={("alpha", "a4"), ("beta", "b1")},
    )
    dispatcher = _dispatcher()

    assert dispatcher.auto_decompose_tick(3) == 0
    assert attempts == [("alpha", "a1"), ("alpha", "a2"), ("alpha", "a3")]

    attempts.clear()
    assert dispatcher.auto_decompose_tick(3) == 2
    assert attempts == [("beta", "b1"), ("alpha", "a4"), ("alpha", "a1")]


def test_cap_larger_than_queue_never_retries_same_task_within_tick(monkeypatch):
    board_tasks = {"alpha": ["a1"], "beta": []}
    attempts = []
    _install_fake_decomposer(monkeypatch, board_tasks, attempts)
    dispatcher = _dispatcher()

    assert dispatcher.auto_decompose_tick(3) == 0
    assert attempts == [("alpha", "a1")]

    attempts.clear()
    assert dispatcher.auto_decompose_tick(3) == 0
    assert attempts == [("alpha", "a1")]
