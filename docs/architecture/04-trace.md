# 第四节：结构化 Trace 系统设计

## 4.1 设计目标

- 每一次层间 PDU 传递自动产出 trace，**零手动埋点**
- 多种输出格式同时工作（btsnoop + JSON + 内存），互不干扰
- trace 开销可控：生产环境可关闭 decode，只记录原始字节
- 与状态机日志统一汇入同一个 trace 管道

## 4.2 核心数据模型

```python
@dataclass(frozen=True)
class TraceEvent:
    timestamp: float                  # time.monotonic()
    wall_clock: datetime              # datetime.now(UTC)，用于 btsnoop
    source_layer: str                 # "transport" | "hci" | "l2cap" | "att" | ...
    direction: Direction              # UP (toward host) | DOWN (toward controller)
    raw_bytes: bytes                  # 原始 PDU 字节
    decoded: dict[str, Any] | None    # 可选解码结果（关闭时为 None）
    connection_handle: int | None     # 关联的 HCI connection handle
    metadata: dict[str, Any]          # 扩展字段（如 L2CAP CID, ATT opcode）

class Direction(Enum):
    UP = "host ← controller"
    DOWN = "host → controller"
```

## 4.3 Trace 管道架构

```
SAP 调用点              TraceSystem              TraceSink(s)
─────────               ───────────              ───────────
                                                 ┌─ BtsnoopSink → .cfa file
HCI.send_acl ──┐                                 │
               ├──► trace.emit(event) ──► fan-out ├─ PcapngSink → .pcapng file
L2CAP.on_data ─┤                                 │
               ├──►                              ├─ JsonSink → .jsonl file
ATT.send_pdu ──┘                                 │
                                                 ├─ RingBufferSink → 内存（REPL 查看）
StateMachine ──────► trace.emit(event) ──► fan-out │
                                                 └─ CallbackSink → 用户自定义
```

### TraceSystem

```python
class TraceSink(Protocol):
    async def on_trace(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...

class TraceSystem:
    def __init__(self) -> None: ...
    def add_sink(self, sink: TraceSink) -> None: ...
    def remove_sink(self, sink: TraceSink) -> None: ...
    def emit(self, event: TraceEvent) -> None: ...   # 非阻塞，投入内部队列
    async def start(self) -> None: ...                # 启动后台分发任务
    async def stop(self) -> None: ...                 # flush + close 所有 sink
    @property
    def enabled(self) -> bool: ...
    @enabled.setter
    def enabled(self, value: bool) -> None: ...
```

`emit()` 是同步非阻塞：将 event 投入 `asyncio.Queue`，后台 task 异步分发给所有 sink。协议层的 hot path 不会因 trace IO 阻塞。

## 4.4 各 Sink 实现

### BtsnoopSink

```python
class BtsnoopSink:
    """输出标准 btsnoop 格式文件"""
    def __init__(self, path: str | Path) -> None: ...
    # btsnoop header: 16 bytes magic + version + datalink type (H4)
    # 每条 record: original_length + included_length + flags + drops + timestamp + data
    # flags: 0=sent, 1=received (对应 Direction)
    # timestamp: microseconds since 2000-01-01
```

兼容性目标：
- Android `bluetooth_hci_snoop.cfa` 格式完全一致
- Wireshark `File → Open` 直接打开，所有 HCI 层 PDU 正确解析
- `btmon` 格式兼容

### PcapngSink

```python
class PcapngSink:
    """输出 pcapng 格式，支持多接口和注释"""
    def __init__(self, path: str | Path) -> None: ...
    # Section Header Block → Interface Description Block (DLT_BLUETOOTH_HCI_H4_WITH_PHDR)
    # Enhanced Packet Block per trace event
    # 支持 Custom Block 写入解码元数据
```

### JsonSink

```python
class JsonSink:
    """输出 JSON Lines 格式，每行一条 trace event"""
    def __init__(self, path: str | Path, decode: bool = True) -> None: ...
    # 格式：{"ts": 1712900000.123, "layer": "hci", "dir": "down",
    #        "hex": "01030c00", "decoded": {"opcode": "HCI_Reset"}, ...}
```

### RingBufferSink

```python
class RingBufferSink:
    """内存环形缓冲，REPL 和调试用"""
    def __init__(self, capacity: int = 1000) -> None: ...
    def recent(self, n: int = 20) -> list[TraceEvent]: ...
    def filter(self, layer: str | None = None,
               direction: Direction | None = None) -> list[TraceEvent]: ...
    def dump(self) -> str: ...   # 人读格式的文本摘要
```

### CallbackSink

```python
class CallbackSink:
    """用户自定义回调"""
    def __init__(self, callback: Callable[[TraceEvent], Awaitable[None]]) -> None: ...
```

## 4.5 SAP 自动 Trace 机制

Trace 不是在每层手动调用 `trace.emit()`，而是在 SAP 基类中自动注入。所有 SAP 调用经过一层薄代理：

```python
class TracingProxy:
    """装饰一个 SAP 实现，自动在调用前后 emit TraceEvent"""

    def __init__(self, target: Any, layer: str,
                 direction: Direction, trace: TraceSystem) -> None: ...
```

组装时由 `Stack` 自动包装：

```python
# Stack 内部组装逻辑（伪码）
hci_impl = HCIController(transport=transport)
traced_hci = TracingProxy(hci_impl, layer="hci", direction=DOWN, trace=trace_system)
l2cap = L2CAPManager(hci=traced_hci)  # L2CAP 看到的是 traced proxy
```

上层无感知，trace 能力由架构自动提供。

## 4.6 Trace 与状态机的统一

状态机转换事件也汇入 `TraceSystem`：

```python
class StateMachineTraceBridge(StateMachineObserver[S, E]):
    """将状态机转换事件转为 TraceEvent"""

    def on_transition(self, sm_name: str, transition: Transition[S, E]) -> None:
        self.trace.emit(TraceEvent(
            source_layer=f"sm:{sm_name}",
            direction=Direction.UP,  # 内部事件统一标记为 UP
            raw_bytes=b"",
            decoded={
                "from": transition.from_state.name,
                "to": transition.to_state.name,
                "event": transition.event.name,
            },
            ...
        ))
```

这意味着在 JSON trace 中，协议 PDU 和状态机转换交织在同一时间线上，复现问题时可以看到"收到什么包 → 状态怎么变"的完整因果链。

## 4.7 可追踪边界矩阵

并非所有 SAP 方法都产出相同类型的 trace。下表明确各边界的 trace 行为：

| 边界 | 代表方法 | trace 类型 | `raw_bytes` | Sink 消费 |
|------|----------|-----------|-------------|-----------|
| Transport ↔ HCI | `send(bytes)` / `on_transport_data(bytes)` | PDU | 有，原始 HCI packet | 全部 Sink |
| HCI ↔ L2CAP | `send_acl_data()` / `on_acl_data()` | PDU | 有，ACL payload | 全部 Sink |
| L2CAP ↔ ATT/SMP | `channel.send()` / `on_data()` | PDU | 有，L2CAP payload | JsonSink, RingBuffer |
| L2CAP ↔ SDP/RFCOMM | `channel.send()` / `on_data()` | PDU | 有，L2CAP payload | JsonSink, RingBuffer |
| 状态机转换 | `StateMachine.transition()` | Runtime | 空 | JsonSink, RingBuffer |
| 控制操作 | `pair()` / `register_fixed_channel()` / `open_le_coc()` | Runtime | 空 | JsonSink, RingBuffer |

**说明**：

- **PDU trace**：携带 `raw_bytes`，所有 Sink 均可消费。BtsnoopSink / PcapngSink 仅消费 `source_layer="transport"` 或 `source_layer="hci"` 的 PDU trace，因为 btsnoop/pcapng 格式仅定义了 HCI 层数据链路。
- **Runtime trace**：`raw_bytes=b""`，`decoded` 字段携带结构化信息。BtsnoopSink / PcapngSink 自动忽略（按 `source_layer` 过滤）。JsonSink 和 RingBufferSink 同时消费 PDU 和 Runtime trace，在同一时间线上呈现完整因果链。

TracingProxy 对两种 trace 使用相同的 `TraceEvent` 数据模型，不需要区分子类型。Sink 侧按 `source_layer` 和 `raw_bytes` 是否为空自行决定是否处理。

## 4.8 性能考量

| 场景 | 策略 |
|------|------|
| 高吞吐（如 A2DP 数据流） | `trace.enabled = False` 关闭 trace，零开销 |
| 生产调试 | 只启用 BtsnoopSink，不做 decode（`decoded=None`），开销最小 |
| 开发调试 | 启用 RingBufferSink + JsonSink + 全量 decode |
| REPL 交互 | `stack.trace.ring.recent(20)` 查看最近 20 条 |
| 长时间运行 | RingBuffer 自动淘汰旧条目；文件 sink 支持 rotation（可选） |
