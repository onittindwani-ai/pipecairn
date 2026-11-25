"""Runtime context shared by the API and the worker: settings, database, adapters, model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from pipecairn import clock
from pipecairn.config import Settings
from pipecairn.models import State
from pipecairn.offline_llm import OfflineBackend
from pipecairn.registry import AdapterSet, build_adapters, build_registry
from sendora_core.costs import CostTracker
from sendora_core.llm import LLM, build_llm
from sendora_core.settings import Mode


@dataclass
class Ctx:
    settings: Settings
    factory: sessionmaker[Session]
    adapters: AdapterSet | Any = None
    registry: Any = None
    directory: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.registry = self.registry or build_registry(self.settings, Path(self.settings.handoff_dir))
        if self.adapters is None:
            self.adapters = build_adapters(self.settings, self.registry, Path(self.settings.handoff_dir))
        if not self.directory:
            f = Path(self.settings.seed_dir) / "seed.json" if self.settings.seed_dir else None
            if f and f.exists():
                self.directory = {c["domain"]: c for c in json.loads(f.read_text())["companies"]}

    def effective(self, session: Session) -> Settings:
        """The kill switch can be turned on in the app, and the mode can be pulled back to draft. Neither can go the other way."""
        kill = session.get(State, "kill_switch")
        mode = session.get(State, "force_draft")
        upd: dict[str, Any] = {}
        if kill and kill.value == "1":
            upd["kill_switch"] = True
        if mode and mode.value == "1":
            upd["mode"] = Mode.DRAFT
        return self.settings.model_copy(update=upd) if upd else self.settings

    def now(self, session: Session):
        return clock.now(session, self.settings.demo_shortcuts)

    def llm(self, session: Session) -> LLM:
        # LLM_BACKEND=offline (default) | fixture | anthropic. The offline stand in is the zero account default.
        # The anthropic path is UNVERIFIED against the real service.
        return build_llm(self.effective(session), CostTracker(session), offline=OfflineBackend())


def set_state(session: Session, key: str, value: str) -> None:
    row = session.get(State, key)
    if row is None:
        session.add(State(key=key, value=value))
    else:
        row.value = value
