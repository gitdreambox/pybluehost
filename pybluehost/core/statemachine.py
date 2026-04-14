from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar

from pybluehost.core.errors import InvalidTransitionError

S = TypeVar("S", bound=Enum)
E = TypeVar("E", bound=Enum)


@dataclass(frozen=True)
class Transition(Generic[S, E]):
    timestamp: float
    from_state: S
    event: E
    to_state: S


class StateMachineObserver(Protocol):
    def on_transition(self, sm_name: str, transition: Transition) -> None: ...  # type: ignore[type-arg]


@dataclass
class _Rule:
    to_state: Any
    action: Callable[..., Awaitable[None]] | None


class StateMachine(Generic[S, E]):
    def __init__(self, name: str, initial: S) -> None:
        self._name = name
        self._state: S = initial
        self._transitions: dict[tuple[S, E], _Rule] = {}
        self._timeouts: dict[S, tuple[float, E]] = {}
        self._history: list[Transition[S, E]] = []
        self._observers: list[StateMachineObserver] = []
        self._timeout_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> S:
        return self._state

    @property
    def history(self) -> list[Transition[S, E]]:
        return list(self._history)

    def add_transition(
        self,
        from_state: S,
        event: E,
        to_state: S,
        action: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._transitions[(from_state, event)] = _Rule(to_state=to_state, action=action)

    def set_timeout(self, state: S, seconds: float, timeout_event: E) -> None:
        self._timeouts[state] = (seconds, timeout_event)

    def add_observer(self, observer: StateMachineObserver) -> None:
        self._observers.append(observer)

    async def fire(self, event: E, **context: object) -> None:
        key = (self._state, event)
        rule = self._transitions.get(key)
        if rule is None:
            raise InvalidTransitionError(
                sm_name=self._name,
                from_state=self._state.name,
                event=event.name,
            )

        from_state = self._state
        self._cancel_timeout()
        self._state = rule.to_state

        transition = Transition(
            timestamp=time.monotonic(),
            from_state=from_state,
            event=event,
            to_state=rule.to_state,
        )
        self._history.append(transition)

        for obs in self._observers:
            obs.on_transition(self._name, transition)

        if rule.action is not None:
            await rule.action(**context)

        self._arm_timeout()

    def _arm_timeout(self) -> None:
        timeout_cfg = self._timeouts.get(self._state)
        if timeout_cfg is None:
            return
        seconds, timeout_event = timeout_cfg

        async def _fire_timeout() -> None:
            await asyncio.sleep(seconds)
            await self.fire(timeout_event)

        self._timeout_task = asyncio.ensure_future(_fire_timeout())

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None
