# 第三节：状态机框架设计

## 3.1 设计目标

蓝牙协议充满有状态交互——连接建立、配对流程、信道协商，每个都是一个状态机。PyBlueHost 要求：

- 状态和转换**必须显式定义**，不能散落在 if/else 和 bool flag 中
- 每次转换自动记录日志，出问题时可回溯完整状态历史
- 超时是一等公民——进入某状态后 N 秒无响应，自动触发超时事件
- 非法转换不是静默忽略，而是立即报错

## 3.2 核心 API

```python
S = TypeVar("S", bound=Enum)  # 状态类型
E = TypeVar("E", bound=Enum)  # 事件类型

class StateMachine(Generic[S, E]):
    def __init__(self, name: str, initial: S): ...

    # 定义转换规则
    def add_transition(self, from_state: S, event: E, to_state: S,
                       action: Callable[..., Awaitable] | None = None) -> None: ...

    # 定义超时守卫
    def set_timeout(self, state: S, seconds: float, timeout_event: E) -> None: ...

    # 触发事件
    async def fire(self, event: E, **context) -> None: ...

    # 当前状态
    @property
    def state(self) -> S: ...

    # 状态转换历史
    @property
    def history(self) -> list[Transition[S, E]]: ...

    # 注册观察者（用于 Trace 系统对接）
    def add_observer(self, observer: StateMachineObserver[S, E]) -> None: ...

@dataclass(frozen=True)
class Transition(Generic[S, E]):
    timestamp: float
    from_state: S
    event: E
    to_state: S
```

## 3.3 HCI 连接状态机示例

```python
class ConnState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ENCRYPTING = auto()
    ENCRYPTED = auto()
    DISCONNECTING = auto()

class ConnEvent(Enum):
    CREATE_CONNECTION = auto()
    CONNECT_COMPLETE = auto()
    CONNECT_FAILED = auto()
    START_ENCRYPTION = auto()
    ENCRYPTION_COMPLETE = auto()
    ENCRYPTION_FAILED = auto()
    DISCONNECT = auto()
    DISCONNECT_COMPLETE = auto()
    TIMEOUT = auto()

# 构建状态机
sm = StateMachine("hci_connection", ConnState.DISCONNECTED)

sm.add_transition(ConnState.DISCONNECTED, ConnEvent.CREATE_CONNECTION, ConnState.CONNECTING)
sm.add_transition(ConnState.CONNECTING,   ConnEvent.CONNECT_COMPLETE,  ConnState.CONNECTED)
sm.add_transition(ConnState.CONNECTING,   ConnEvent.CONNECT_FAILED,    ConnState.DISCONNECTED)
sm.add_transition(ConnState.CONNECTING,   ConnEvent.TIMEOUT,           ConnState.DISCONNECTED)
sm.add_transition(ConnState.CONNECTED,    ConnEvent.START_ENCRYPTION,  ConnState.ENCRYPTING)
sm.add_transition(ConnState.ENCRYPTING,   ConnEvent.ENCRYPTION_COMPLETE, ConnState.ENCRYPTED)
sm.add_transition(ConnState.ENCRYPTING,   ConnEvent.ENCRYPTION_FAILED, ConnState.CONNECTED)
sm.add_transition(ConnState.ENCRYPTED,    ConnEvent.DISCONNECT,        ConnState.DISCONNECTING)
sm.add_transition(ConnState.CONNECTED,    ConnEvent.DISCONNECT,        ConnState.DISCONNECTING)
sm.add_transition(ConnState.DISCONNECTING, ConnEvent.DISCONNECT_COMPLETE, ConnState.DISCONNECTED)

# 超时：CONNECTING 状态 30 秒无响应自动断开
sm.set_timeout(ConnState.CONNECTING, 30.0, ConnEvent.TIMEOUT)
sm.set_timeout(ConnState.ENCRYPTING, 10.0, ConnEvent.TIMEOUT)
```

## 3.4 状态机可视化

```
                          CREATE_CONNECTION
  DISCONNECTED ──────────────────────────────► CONNECTING
       ▲                                        │  │
       │  DISCONNECT_COMPLETE                   │  │ CONNECT_FAILED
       │◄──────────────────────────┐            │  │ / TIMEOUT
       │                           │            │  │
       ◄───────────────────────────┼────────────┘  │
       │                           │               │
       │                    DISCONNECTING           │
       │                      ▲    ▲               │
       │          DISCONNECT  │    │               │
       │                      │    │               │
       │                ENCRYPTED  CONNECTED ◄─────┘
       │                   ▲         │
       │  ENCRYPTION_COMPLETE        │ START_ENCRYPTION
       │                   │         ▼
       │                ENCRYPTING
       │                   │
       │  ENCRYPTION_FAILED│
       │                   ▼
       └───────────── CONNECTED
```

## 3.5 自动日志输出

每次 `fire()` 调用，状态机自动产出结构化日志：

```
[2026-04-12T10:00:01.123] [SM:hci_connection:0x0040] DISCONNECTED → CONNECTING via CREATE_CONNECTION
[2026-04-12T10:00:01.123] [SM:hci_connection:0x0040] timeout armed: 30.0s → TIMEOUT
[2026-04-12T10:00:01.456] [SM:hci_connection:0x0040] CONNECTING → CONNECTED via CONNECT_COMPLETE
[2026-04-12T10:00:01.456] [SM:hci_connection:0x0040] timeout disarmed
```

日志通过 `StateMachineObserver` 接口发出，`trace.py` 中的 `TraceSystem` 自动注册为观察者，无需手动接线。

## 3.6 非法转换处理

```python
# 当前状态 CONNECTED，不应该收到 CONNECT_COMPLETE
await sm.fire(ConnEvent.CONNECT_COMPLETE)
# 抛出 InvalidTransitionError:
#   "hci_connection:0x0040: no transition from CONNECTED via CONNECT_COMPLETE"
#   附带完整 history 快照，方便定位问题
```

## 3.7 蓝牙中需要状态机的关键位置

| 位置 | 状态数 | 典型状态 |
|------|--------|---------|
| HCI 连接 | ~6 | Disconnected → Connecting → Connected → Encrypted |
| SMP 配对 | ~8 | Idle → Phase1 → Phase2（SC/Legacy）→ Phase3 → Bonded |
| L2CAP 信道（Classic） | ~5 | Closed → Config → Open → Disconnecting |
| L2CAP CoC（BLE） | ~4 | Closed → Connecting → Open → Disconnecting |
| RFCOMM DLC | ~4 | Closed → Opening → Open → Closing |
| GAP Discovery | ~3 | Idle → Inquiring/Scanning → Complete |
| GAP Advertising | ~3 | Idle → Advertising → Stopped |

每个位置用同一个 `StateMachine[S, E]` 框架，实现一致，调试统一。
