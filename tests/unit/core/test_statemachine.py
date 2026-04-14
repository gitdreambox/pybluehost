import asyncio
from enum import Enum, auto

import pytest

from pybluehost.core.errors import InvalidTransitionError
from pybluehost.core.statemachine import StateMachine, Transition, StateMachineObserver


class S(Enum):
    IDLE = auto()
    ACTIVE = auto()
    DONE = auto()


class E(Enum):
    START = auto()
    FINISH = auto()
    RESET = auto()
    TIMEOUT = auto()


class TestStateMachineBasic:
    def test_initial_state(self):
        sm = StateMachine("test", S.IDLE)
        assert sm.state == S.IDLE

    def test_name(self):
        sm = StateMachine("my_sm", S.IDLE)
        assert sm.name == "my_sm"

    @pytest.mark.asyncio
    async def test_simple_transition(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        await sm.fire(E.START)
        assert sm.state == S.ACTIVE

    @pytest.mark.asyncio
    async def test_two_transitions(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert sm.state == S.DONE

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        with pytest.raises(InvalidTransitionError, match="no transition from IDLE via FINISH"):
            await sm.fire(E.FINISH)

    @pytest.mark.asyncio
    async def test_history_recorded(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert len(sm.history) == 2
        assert sm.history[0].from_state == S.IDLE
        assert sm.history[0].event == E.START
        assert sm.history[0].to_state == S.ACTIVE
        assert sm.history[1].from_state == S.ACTIVE
        assert sm.history[1].event == E.FINISH
        assert sm.history[1].to_state == S.DONE

    @pytest.mark.asyncio
    async def test_transition_has_timestamp(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        await sm.fire(E.START)
        assert isinstance(sm.history[0].timestamp, float)
        assert sm.history[0].timestamp > 0


class TestStateMachineActions:
    @pytest.mark.asyncio
    async def test_action_called_on_transition(self):
        called_with: list[dict] = []

        async def on_start(**ctx: object) -> None:
            called_with.append(dict(ctx))

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE, action=on_start)
        await sm.fire(E.START, handle=0x40)
        assert len(called_with) == 1
        assert called_with[0]["handle"] == 0x40

    @pytest.mark.asyncio
    async def test_action_not_called_on_wrong_transition(self):
        called = False

        async def on_start(**ctx: object) -> None:
            nonlocal called
            called = True

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE, action=on_start)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        await sm.fire(E.START)
        called = False
        await sm.fire(E.FINISH)
        assert called is False


class TestStateMachineObserverPattern:
    @pytest.mark.asyncio
    async def test_observer_notified(self):
        transitions: list[Transition] = []

        class TestObserver(StateMachineObserver):
            def on_transition(self, sm_name: str, transition: Transition) -> None:
                transitions.append(transition)

        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_observer(TestObserver())
        await sm.fire(E.START)
        assert len(transitions) == 1
        assert transitions[0].from_state == S.IDLE
        assert transitions[0].to_state == S.ACTIVE


class TestStateMachineTimeout:
    @pytest.mark.asyncio
    async def test_timeout_fires_event(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.TIMEOUT, S.IDLE)
        sm.set_timeout(S.ACTIVE, 0.05, E.TIMEOUT)
        await sm.fire(E.START)
        assert sm.state == S.ACTIVE
        await asyncio.sleep(0.1)
        assert sm.state == S.IDLE

    @pytest.mark.asyncio
    async def test_timeout_cancelled_on_transition(self):
        sm = StateMachine("test", S.IDLE)
        sm.add_transition(S.IDLE, E.START, S.ACTIVE)
        sm.add_transition(S.ACTIVE, E.FINISH, S.DONE)
        sm.add_transition(S.ACTIVE, E.TIMEOUT, S.IDLE)
        sm.set_timeout(S.ACTIVE, 0.05, E.TIMEOUT)
        await sm.fire(E.START)
        await sm.fire(E.FINISH)
        assert sm.state == S.DONE
        await asyncio.sleep(0.1)
        assert sm.state == S.DONE  # timeout should NOT have fired
