# VirtualRadio 设计文档

| 项 | 值 |
|----|----|
| 状态 | 已批准 |
| 日期 | 2026-04-27 |
| 责任方 | HCI 层 / 测试基础设施 |
| 前置依赖 | [pytest-transport-selection-design.md](./pytest-transport-selection-design.md) |
| 范围 | 让 `VirtualController` 成为完整 controller，支持 LE/BR-EDR adv/scan/inquiry/page/ACL；通过独立 daemon 子进程让多个 VC（同进程或跨进程）互联 |

## 1. 目标

让 PyBlueHost 在不接真硬件的情况下能跑**完整端到端协议测试**：两个 `VirtualController` 通过共享空气信道互相收发广播、做 inquiry/page、建立连接、双向收发 ACL（ATT / L2CAP / SMP / RFCOMM / SDP 自动跑在 ACL 上）。

具体要让以下场景"真协议路径"工作（替代当前 `gatt_browser` / `sdp_browser` 的 demo trick）：

- VC A 发 LE adv → VC B scan 能收到 `LE_Advertising_Report`
- VC A 发 inquiry → 所有 inquiry-scan 模式的 VC B/C/... 都被发现
- VC A 发起 page → 处于 page-scan 模式的 VC B 接受连接
- 连接建立后两端 ACL 双向收发（host 层 ATT/SDP/RFCOMM 自动可用）
- 同一 host 进程内的多个 VC 互联（pytest 测试 / 单 CLI 内部 peer）
- 不同 host 进程间的 VC 互联（跨终端 demo）

## 2. 边界

**做的事**：
- VC 内实现 LE Link Layer / BR-EDR Link Layer 状态机所需的 HCI command + event 处理
- VirtualRadio daemon：进程外 socket server，承载 PDU 路由
- 客户端 IPCRadio：连入 daemon，把 bus 操作序列化为 socket 消息

**不做的事**（host 一行代码不动）：
- ATT / GATT / L2CAP / SMP / RFCOMM / SDP 任何 host 协议层
- BLEAdvertiser / BLEScanner / BLEConnectionManager / GATTServer / GATTClient 等 host API
- USB / UART transport

只要 VC 把 ACL 双向通了，host 层协议自动可用。

## 3. 架构总览

```
┌──────────────────┐    HCI     ┌──────────────────┐    HCI    ┌──────────────────┐
│ Host Stack A     │ ───cmd──▶  │ VirtualController│           │ VirtualController│ ◀──cmd── │ Host Stack B     │
│ (BLEAdvertiser,  │ ◀──evt───  │       A          │           │       B          │ ──evt──▶ │ (BLEScanner,     │
│  GATTClient,...) │            │  ┌─────────────┐ │           │  ┌─────────────┐ │          │  GATTServer,...) │
└──────────────────┘            │  │ LL state    │ │           │  │ LL state    │ │          └──────────────────┘
                                │  │ machines    │ │           │  │ machines    │ │
                                │  └──────┬──────┘ │           │  └──────┬──────┘ │
                                │         │ IPCRadio          │         │ IPCRadio
                                │         ▼ client            │         ▼ client
                                │   ┌────────────┐            │   ┌────────────┐
                                │   │ asyncio    │            │   │ asyncio    │
                                │   │ Unix socket│            │   │ Unix socket│
                                │   └─────┬──────┘            │   └─────┬──────┘
                                └─────────┼──────────────────────────────┼───────┘
                                          │                              │
                                          ▼                              ▼
                              ┌─────────────────────────────────────────────────┐
                              │  pybluehost.hci._daemon (detached subprocess)    │
                              │  asyncio Unix socket server                      │
                              │  @ /tmp/pybluehost-radio.sock                    │
                              │                                                  │
                              │  RadioDaemon: bus state + per-client coroutine   │
                              │   - _adv_publishers: {addr: AdvPDU}              │
                              │   - _scanners: set of addrs                      │
                              │   - _inquiry_scan_publishers: {addr: EIR}        │
                              │   - _page_scan_listeners: set of addrs           │
                              │   - _acl_pairs: {(addr_a, h_a): (addr_b, h_b)}   │
                              │   - per-VC inbox writers                         │
                              └─────────────────────────────────────────────────┘
```

**核心心智模型**：
- VC 是真控制器：HCI cmd 进 → 跑自己的 LL 状态机 → HCI evt 出
- daemon 是空气：carry PDU，不解释语义；维持最小路由 registry
- daemon **永远是独立子进程**（detached），第一个客户端按需 spawn，idle 30s 自动退出
- 一个 socket 路径 = 一个虚拟蓝牙宇宙；默认 `/tmp/pybluehost-radio.sock` 全场景共享

## 4. Phase 1 vs 不做（YAGNI）

**Phase 1 做**：
- LE：Set_Advertising_Parameters/Data/Enable、Set_Scan_Parameters/Enable、Set_Random_Address、Create_Connection/Cancel、Connection_Update、Start_Encryption + LTK 配套
- BR/EDR：Inquiry/Inquiry_Cancel、Write_Scan_Enable、Write_EIR、Write_COD、Create_Connection、Accept/Reject_Connection_Request、Disconnect、SSP（IO_Capability_Request_*、User_Confirmation_*、User_Passkey_*、Set_Connection_Encryption、Authentication_Requested）
- ACL：HCI ACL Data packet 双向 + Number_Of_Completed_Packets 流控
- 多连接：单 VC 同时多 LE 连接 + 多 BR-EDR 连接 + 混合
- 多 VC 拓扑：daemon 支持 N 个 VC（不只 2）
- daemon 子进程模式 + 自动 spawn + idle timeout
- 同进程内多 VC 互联 + 跨进程 VC 互联（同一 socket 即同一宇宙）

**Phase 1 不做**：
- LE 5.0 Extended Advertising / Periodic Advertising / 2M PHY / Coded PHY
- 多 advertising set（一个 VC 多 adv 同时跑）
- LE Privacy 高级（Resolving List、RPA 解析）
- LE Direct Test Mode（DTM）
- BR/EDR Hold/Sniff/Park/Role_Switch
- BR/EDR SCO/eSCO 音频通道
- Vendor-specific HCI 命令
- 真实 AES-CCM / AES-CMAC 加密（fake：bus 上明文，但 fire `Encryption_Change_Event` 让 host 状态机以为已加密）
- 真实 LE Secure Connections ECDH 密钥协商（fake 出 P-256 keys + 触发对应事件）
- 时序模拟（adv interval / connection interval / inquiry length 真等）
- 错误注入 / 丢包 / 抖动
- 跨主机互联（Phase 3+ TCP backend）
- PTS IUT 适配层（独立后续 plan）

## 5. 模块文件结构

```
pybluehost/hci/
├── virtual.py                ← 已有；保留 VirtualController 主类、_HCIPipe（pytest plan Task 2 内化产物）
│                                本 plan 把 VC 拆为多 mixin 组装入口
├── _virtual_radio.py         ← 新增；模块级 IPCRadio 单例 + get_radio() / reset_virtual_radio()
├── _ipc_radio.py             ← 新增；IPCRadio 客户端类（持有 reader/writer，序列化 bus 操作）
├── _daemon.py                ← 新增；RadioDaemon + python -m 入口
├── _radio_protocol.py        ← 新增；BusCommand/BusEvent dataclass + JSON 编码 + 4-byte length-prefix framing
├── _radio_factory.py         ← 新增；socket path 解析 + spawn + 客户端连接（含竞态保护）
├── _virtual_ll_le.py         ← 新增；VC 的 LE Link Layer mixin
├── _virtual_ll_classic.py    ← 新增；VC 的 BR/EDR Link Layer mixin
├── _virtual_ll_acl.py        ← 新增；VC 的 ACL 通用收发 + flow control
├── _virtual_ll_security.py   ← 新增；fake encryption / SSP 事件
└── _virtual_addresses.py     ← 新增；地址分配（随机 LAP，前缀 AA:BB:CC）+ 显式覆盖

pybluehost/cli/tools/
└── radio.py                  ← 新增；`pybluehost radio {start,status,stop,list}` 子命令组
```

`_` 前缀全部表示模块私有；外部仅从 `pybluehost.hci.virtual` 导入。

## 6. VirtualController 重组（mixin 拼装）

```python
class VirtualController(
    _BasicHandlersMixin,        # 已有 16 个静态查询命令（Reset/Read_BD_ADDR/...）
    _LELinkLayerMixin,          # 新增；LE adv/scan/connect 状态机
    _ClassicLinkLayerMixin,     # 新增；BR/EDR inquiry/page 状态机
    _ACLMixin,                  # 新增；ACL data + Number_Of_Completed_Packets
    _SecurityMixin,             # 新增；fake encryption / SSP
):
    @classmethod
    async def create(
        cls,
        address: BDAddress | None = None,
    ) -> tuple["VirtualController", Transport]:
        """Create a VirtualController, attach to the radio, return (vc, host_transport)."""
        # 1. Allocate or claim address
        if address is None:
            address = _allocate_random_address()
        # 2. Construct VC, init all mixin state
        vc = cls(address=address)
        # 3. Wire host-side and controller-side pipes (uses _HCIPipe from pytest plan Task 2)
        host_t, ctrl_t = _HCIPipe.pair()
        ctrl_t.set_sink(_VCSink(vc))
        await host_t.open()
        await ctrl_t.open()
        # 4. Connect to radio daemon (spawns if needed)
        radio = await get_radio()
        await radio.attach(vc)
        return vc, host_t

    async def close(self) -> None:
        # Disconnect all active connections (fire Disconnection_Complete to peers)
        # Retract all publications
        # Detach from radio
        # Close pipes
        ...
```

**HCI command dispatch 表**扩展到约 50 个 opcode（详见 §11），由各 mixin 提供 handler 字典；VC `__init__` 合并。

## 7. LL 状态机（VC 自身职责）

每个 mixin 维护自己的 LL 子模块状态。bus 不知道这些状态；只承载 PDU。

### 7.1 `_LELinkLayerMixin`

| 状态字段 | 类型 |
|---------|------|
| `_le_adv_params` | `AdvParams \| None` |
| `_le_adv_data` | `bytes` |
| `_le_adv_scan_resp_data` | `bytes` |
| `_le_adv_enabled` | `bool` |
| `_le_random_address` | `BDAddress \| None` |
| `_le_scan_params` | `ScanParams \| None` |
| `_le_scan_enabled` | `bool` |
| `_le_pending_create_connection` | `CreateConnectionParams \| None` |

### 7.2 `_ClassicLinkLayerMixin`

| 状态字段 | 类型 |
|---------|------|
| `_classic_inquiry_active` | `bool` |
| `_classic_inquiry_scan_enabled` | `bool` |
| `_classic_page_scan_enabled` | `bool` |
| `_classic_eir` | `bytes` |
| `_classic_class_of_device` | `int` |
| `_classic_local_name` | `bytes` |

### 7.3 `_ACLMixin`

| 状态字段 | 类型 |
|---------|------|
| `_connections` | `dict[int, ConnectionState]`（handle → state） |
| `_next_handle_counter` | `int`（0x0040 起单调 +1） |

```python
@dataclass
class ConnectionState:
    peer_address: BDAddress
    role: int                  # CENTRAL=0x00, PERIPHERAL=0x01
    link_type: str             # "le" or "classic"
    encrypted: bool = False
    mtu: int = 23              # default ATT MTU; updated by host
```

支持的并行能力（同 VC 同时）：
- 一个 advertising（仅 legacy）
- 一个 scanning
- 一个 inquiry 或 inquiry-scan
- 一个 page-scan
- 多个 LE 连接 + 多个 BR-EDR 连接（混合）
- 同 VC 既 central 又 peripheral

约束：同一对 VC 之间最多一条 ACL link；连接数上限沿用 `total_num_le_acl=8` / `total_num_acl=8`。

### 7.4 `_SecurityMixin`

```python
class _SecurityMixin:
    _pending_ltk_requests: dict[int, LtkRequest]
    _pending_ssp: dict[int, SspState]
```

按 §11 的 fake 路径实现。每个 HCI command 立即回 Command_Status / Command_Complete；通过 daemon 的 `signal` 操作通知对端 VC 触发对应 event。`encrypted` 字段在 `Encryption_Change` 之后翻为 True，但 daemon 上的 ACL 始终明文。

### 7.5 `HCI_Reset` 升级

真控制器 `HCI_Reset` 清空所有 LL 状态。本设计：

- 断开所有连接（无 event；spec 规定 reset 静默清空）；通知 daemon 清理 connection table 中本 VC 相关的所有条目，并 fire `Disconnection_Complete` 给对端
- 撤销所有 publication（adv / inquiry-scan / page-scan）
- 清空所有 mixin 状态到初始值

## 8. 时序模型（瞬时 / instantaneous）

不模拟 adv interval / scan window / connection interval / inquiry length / page timeout。所有事件即时触发：

- adv 启动 → 所有当前 scanning VC 立即收到 `LE_Advertising_Report`
- scanner 启动 → daemon 把当前所有 advertiser 的 PDU 快照立即投递
- create_connection 找到对端 → 两端立即收到 `LE_Connection_Complete`
- 找不到对端 → asyncio.create_task fire `LE_Connection_Complete(status=PAGE_TIMEOUT)`（不真等）

唯一保留的"顺序保证"：HCI command 收到后立即同步回 `Command_Status`，但异步 event（如 `LE_Connection_Complete`）通过 `asyncio.create_task` 调度，确保 host 看到的顺序是 status → event。

## 9. 地址分配

```python
import secrets

_VIRTUAL_NAP = bytes.fromhex("AABB")  # 2 bytes, fixed
_VIRTUAL_UAP = bytes.fromhex("CC")    # 1 byte, fixed
# LAP: 3 bytes random per VC

def _allocate_random_address() -> BDAddress:
    """Return AA:BB:CC:XX:YY:ZZ where XX:YY:ZZ is random per VC."""
    while True:
        lap = secrets.token_bytes(3)
        candidate = BDAddress(_VIRTUAL_NAP + _VIRTUAL_UAP + lap)
        if candidate not in _explicit_addresses_in_use:
            return candidate
```

- 默认随机 LAP（24 bits = 16M 可能值；几百 VC 内 birthday-paradox 概率 < 1‰）
- 显式覆盖：`Stack.virtual(address=BDAddress.from_string("..."))` / `VirtualController.create(address=...)`
- `AA:BB:CC` 前缀醒目可识别；日志中一眼看出"虚拟设备"
- daemon 的地址 → VC 路由表用 BDAddress 作为 key（不依赖对象引用）

## 10. Daemon + IPC 设计

### 10.1 Daemon 单一运行模式 = detached 子进程

第一个客户端进程检测 socket 不存在时 spawn：

```python
subprocess.Popen(
    [sys.executable, "-m", "pybluehost.hci._daemon",
     "--socket", str(socket_path),
     "--idle-timeout", "30"],
    start_new_session=True,        # Linux/macOS: setsid()，daemon 脱离 session
    stdin=subprocess.DEVNULL,
    stdout=open(log_path, "a"),
    stderr=subprocess.STDOUT,
)
# Windows 等价：creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
```

**daemon 不与启动它的客户端绑定生命周期**。生命周期由"是否还有客户端连接"决定，加 idle timeout 兜底。

### 10.2 单 socket 共享所有场景

默认路径：`/tmp/pybluehost-radio.sock`（Windows: `\\.\pipe\pybluehost-radio`）

所有场景共享同一 daemon：
- pytest session（单进程）
- pytest-xdist worker（多进程并行；接受测试间通过 reset 隔离的成本）
- 单 CLI 进程（primary stack + peer stack 都连同一 daemon）
- 跨终端 CLI demo

显式覆盖：`PYBLUEHOST_RADIO=/path/to/custom.sock` 环境变量。仅当确实需要隔离（如同时跑两个独立 test session）时使用。

### 10.3 测试隔离仅靠 reset 命令

```python
# tests/conftest.py — autouse fixture (function-scope)
@pytest.fixture(autouse=True)
async def _reset_virtual_radio_each_test():
    yield
    # After test: send reset to daemon (idempotent)
    # By this point, stack/peer_stack fixtures have already torn down,
    # so any attached VCs have detached normally. Reset is defense-in-depth.
    if _socket_path().exists():
        async with _connect_short() as (r, w):
            await _send_command(w, BusCommand(op="reset", payload={}))
            await _read_event(r)  # wait for ack
```

`BusCommand(op="reset")` 让 daemon 清空所有 bus 状态：
- `_inboxes` 表（应已为空）
- 所有 publication 表（adv / inquiry-scan / page-scan）
- 所有 connection pair
- 内部计数器

不重启 daemon 进程，仅重置状态。语义：**reset 假设此时无 attached client**（pytest 用法的合约）；如有残留 client，reset 会强制把它们的状态清空（client 后续 op 会失败并需重新 attach）。daemon 实现 reset 时遍历 `_inboxes` 主动 close socket，确保下个测试干净开始。

### 10.4 启动竞态保护

多客户端同时尝试 spawn 时：

```python
async def get_or_spawn_radio(socket_path: Path, max_wait: float = 2.5):
    deadline = asyncio.get_event_loop().time() + max_wait
    while True:
        try:
            return await asyncio.open_unix_connection(str(socket_path))
        except (FileNotFoundError, ConnectionRefusedError):
            pass

        if not socket_path.exists():
            _spawn_detached_daemon(socket_path)

        if asyncio.get_event_loop().time() >= deadline:
            raise RuntimeError(f"Daemon at {socket_path} not reachable in {max_wait}s")

        await asyncio.sleep(0.05)
```

第二个 daemon 进程 `bind()` 失败立即退出（`EADDRINUSE`）。客户端轮询连接，总会连上活着的那个。残留 socket 文件在 spawn 前检测：若不可连接，`unlink` 后再 spawn。

### 10.5 协议 framing

```
[4 bytes big-endian length] [N bytes JSON-encoded BusCommand or BusEvent]
```

```python
@dataclass
class BusCommand:
    """Sent by client to daemon."""
    op: str        # "attach" | "detach" | "publish_adv" | "subscribe_adv" |
                   # "create_connection_pair" | "deliver_acl" | "reset" | ...
    payload: dict  # primitive types only (str/int/bytes hex / list / dict)


@dataclass
class BusEvent:
    """Sent by daemon to client."""
    kind: str      # "adv_received" | "connection_request" | "acl_data" |
                   # "ssp_signal" | "ack" | "error" | ...
    payload: dict
```

JSON 选型理由：stdlib only、调试可读、性能足够（瞬时模型 + 非密集 op）。`bytes` 字段以 hex 字符串编码。

### 10.6 Per-client coroutine

```python
class RadioDaemon:
    async def _handle_client(self, reader, writer):
        address: BDAddress | None = None
        try:
            cmd = await read_command(reader)
            assert cmd.op == "attach"
            address = BDAddress.from_string(cmd.payload["address"])
            if address in self._inboxes:
                # Address collision — reject; client must allocate different addr
                await write_event(writer, BusEvent(
                    kind="error",
                    payload={"detail": f"address {address} already attached"},
                ))
                return
            self._inboxes[address] = writer
            await write_event(writer, BusEvent(kind="ack", payload={}))
            async for cmd in iter_commands(reader):
                await self._dispatch(cmd, address)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass  # client crash / disconnect — clean up below
        except Exception as e:
            await write_event(writer, BusEvent(kind="error", payload={"detail": str(e)}))
        finally:
            if address is not None:
                self._inboxes.pop(address, None)
                self._cleanup_vc_state(address)  # retract publications, close connections
            writer.close()
            await writer.wait_closed()
            self._update_idle_state()  # may schedule shutdown
```

`_cleanup_vc_state(address)`：撤销该 VC 的 adv 发布、inquiry-scan 发布、page-scan 监听；遍历 `_acl_pairs` 找出该 VC 涉及的所有连接，给对端 fire `Disconnection_Complete`（reason=CONNECTION_TIMEOUT）后从表中移除。

### 10.7 Idle timeout

```python
async def _idle_watchdog(self):
    if self._idle_timeout <= 0:
        return  # 0 or negative means "never timeout"; watchdog never runs
    while True:
        await asyncio.sleep(5)
        if not self._inboxes and self._idle_since is not None:
            elapsed = time.monotonic() - self._idle_since
            if elapsed >= self._idle_timeout:
                asyncio.get_event_loop().stop()
                return
```

`--idle-timeout=0` 表示永不超时（开发/调试 / systemd-managed daemon）。默认 30s。

### 10.8 客户端崩溃恢复

客户端进程异常退出 → socket 关闭 → daemon 收到 `ConnectionResetError` / `EOF` → from `_inboxes` 移除该 VC → 调 `_cleanup_vc_state(addr)`：撤销该 VC 所有 publication；关闭它的所有连接（fire `Disconnection_Complete` 给对端 VC）。

## 11. HCI command/event 覆盖矩阵

### 11.1 Command（约 44 个）

详细 opcode 列表：见 §11.2 子节。按 OGF 分组：

- **LE OGF=0x08**：Set_Event_Mask、Read_Buffer_Size、Read_Local_Supported_Features、Set_Random_Address、Set_Advertising_Parameters、Set_Advertising_Data、Set_Scan_Response_Data、Set_Advertising_Enable、Set_Scan_Parameters、Set_Scan_Enable、Create_Connection、Create_Connection_Cancel、Connection_Update、Start_Encryption、Long_Term_Key_Request_Reply、Long_Term_Key_Request_Negative_Reply、Read_Supported_States、Read/Write_Suggested_Default_Data_Length（共 19）
- **Link Control OGF=0x01**：Inquiry、Inquiry_Cancel、Create_Connection、Disconnect、Accept_Connection_Request、Reject_Connection_Request、Link_Key_Request_Reply、Link_Key_Request_Negative_Reply、Authentication_Requested、Set_Connection_Encryption、IO_Capability_Request_Reply / Negative_Reply、User_Confirmation_Request_Reply / Negative_Reply、User_Passkey_Request_Reply / Negative_Reply（共 15）
- **Controller & Baseband OGF=0x03**：HCI_Reset（升级）、Set_Event_Mask、Set_Event_Filter、Change_Local_Name、Write_Page_Timeout、Write_Scan_Enable、Write_Class_Of_Device、Host_Buffer_Size、Host_Number_Of_Completed_Packets、Write_Inquiry_Mode、Write_Extended_Inquiry_Response、Write_Simple_Pairing_Mode（共 12）
- **Information OGF=0x04**：保留当前 5 个（Read_Local_Version 等），不变
- **未列出的命令**返回 `UNKNOWN_HCI_COMMAND=0x01`

### 11.2 Event（约 17 个）

- **General**：Connection_Complete、Connection_Request、Disconnection_Complete、Encryption_Change、Command_Complete、Command_Status、Number_Of_Completed_Packets
- **Inquiry**：Inquiry_Result_with_RSSI、Extended_Inquiry_Result、Inquiry_Complete
- **SSP**：IO_Capability_Request、IO_Capability_Response、User_Confirmation_Request、User_Passkey_Request、Simple_Pairing_Complete
- **LE Meta Event 子代码**：LE_Connection_Complete、LE_Advertising_Report、LE_Connection_Update_Complete、LE_Long_Term_Key_Request

### 11.3 ACL Data path（不走 command 表）

- Inbound：`HCI_ACL_DATA_PACKET (0x02)` packet → `VC._on_host_acl_packet()` → daemon `deliver_acl` → 对端 `_receive_acl()` → 包 HCI ACL Data event 给对端 host
- Outbound：每 outbound packet 立即 fire `Number_Of_Completed_Packets_Event(handle, count=1)` 给本 host
- packet 的 PB / BC flags 原样保留；host 端 L2CAP 真分片真重组

## 12. CLI 集成

### 12.1 `pybluehost radio` 子命令

```bash
pybluehost radio start [--idle-timeout=N]    # 显式启 daemon（一般不需要，自动 spawn）
pybluehost radio status                       # 列出 attached VC + 当前 publications
pybluehost radio stop                         # 优雅关闭（发送 shutdown 命令）
pybluehost radio list                         # 扫描 /tmp/pybluehost-radio*.sock 列出活动 daemon
```

### 12.2 `--transport=virtual` 路径

`pybluehost/cli/_transport.py` 的 `parse_transport_arg("virtual")` 升级为：
```python
if s == "virtual":
    radio = await get_or_spawn_radio(_default_socket_path())
    vc, host_t = await VirtualController.create(radio=radio)
    return host_t
```

`virtual_peer_with` （CLI 内部 helper）保持不变 —— 它创建第二个 Stack，第二个 Stack 内部自动连入同一 daemon，自然互联。`gatt_browser` 等 demo trick 自动升级为真协议路径。

## 13. 测试策略

### 13.1 三层金字塔

| 层 | 位置 | 跑什么 | 用什么基础设施 |
|----|------|-------|---------------|
| **VC mixin 单元** | `tests/unit/hci/test_virtual_*.py` | 每个 mixin 的 LL 状态机：HCI command in → 期望 HCI event out + 期望 bus 操作 | mock `IPCRadio`（capture-only），不启 daemon |
| **协议单元** | `tests/unit/hci/test_radio_protocol.py` | `BusCommand/BusEvent` 序列化、framing | 纯函数测试，无 daemon |
| **Daemon 单元** | `tests/unit/hci/test_daemon.py` | 启子进程 daemon、attach/detach、reset、idle timeout、并发 spawn 竞态 | 真 subprocess + 临时 socket |
| **集成（同进程多 VC）** | `tests/integration/virtual_radio/` | 两个 Stack 通过共享 daemon 跑端到端：scan→connect→ATT 读、inquiry→page、SSP 配对 | pytest plan 已交付 `stack` + `peer_stack` fixture |
| **集成（跨进程多 VC）** | `tests/integration/virtual_radio_ipc/` | 起两个 pytest 子进程跑两端，验证跨进程 GATT 通信 | pytest 启子进程 + 自定义 socket 路径 |

### 13.2 Pytest fixture 集成

依赖 [pytest-transport-selection plan](../plans/pytest-transport-selection.md) 已交付的 `stack` / `peer_stack` fixture。本 plan **不修改** fixture 接口；仅追加：

- function-scope autouse：每测试结束发 reset 命令清空 daemon 状态。Daemon 由第一个调用 `Stack.virtual()` 的测试触发**懒启动**（`get_or_spawn_radio` 内部 spawn detached subprocess）；session 结束时 daemon 进入 idle，30s 后自退（pytest session 退出后即使有残留也会自然清理）
- session-scope teardown（可选）：发送 `BusCommand(op="shutdown")` 主动让 daemon 退出，避免 idle 30s 浪费

### 13.3 真硬件等价性（forward compatibility）

`tests/integration/virtual_radio/` 的测试**不**写 `virtual_only` marker。它们既能在 `--transport=virtual` 跑（共享 daemon），也能在 `--transport=usb` + 双适配器（`peer_stack`）上跑。CI 永远只跑 virtual 路径；持有双适配器的开发机能手动跑硬件路径做等价性验证。

跨进程测试 `tests/integration/virtual_radio_ipc/` 标 `@pytest.mark.ipc`（本 plan 在 pytest plan 的 markers 列表上**追加**这一项；同步更新 `pyproject.toml`）；CI 跑（保证 daemon + 协议 working），本地开发可 `pytest -m "not ipc"` 跳过。

## 14. 与 pytest-transport-selection plan 的边界

VirtualRadio plan **依赖**已交付：
- `Stack.virtual()` 工厂、`StackMode.VIRTUAL` 枚举
- `VirtualController.create()` async classmethod（本 plan 升级为"挂入共享 daemon"）
- `_HCIPipe`（已内化的 host-VC pipe）
- `stack` / `peer_stack` 测试 fixture
- `virtual_only` / `real_hardware_only` markers

VirtualRadio plan **不修改**：
- 任何 host 层代码（`ble/`、`classic/`、`l2cap/`、`gap.py`、`stack.py` 的 `_build`）
- pytest plan 已确定的 fixture / marker 接口
- 任何真实 transport（USB / UART）相关代码

## 15. 后续 Plan 立项 forward-reference

不在本 Phase 1 范围、待独立 brainstorming 立项：

| 后续工作 | 占位 | 主要内容 |
|---------|------|---------|
| 错误注入 / 网络异常仿真 | `error-injection-design.md`（待） | daemon 层 plug-in：按规则丢包 / 重排 / 延迟 / 损坏 PDU |
| 跨主机 VirtualRadio | `cross-host-radio-design.md`（待） | TCP backend；多机互联仿真 |
| Multi-tenant daemon | （待） | 单 daemon 服务多 socket / 多命名空间，避免每场景一个 daemon 进程 |
| LE Extended Advertising | `le-extended-adv-design.md`（待） | 多 advertising set / Extended_Adv 系列命令 |
| PTS IUT 适配层 | `pts-iut-design.md`（待） | 把 PIXIT/IXIT 配置映射到 VirtualRadio 测试场景 |
| 真硬件桥接 | `radio-hardware-bridge-design.md`（待） | daemon 接 raw HCI sniffer 让虚拟 VC 与真硬件设备共一个 bus |

## 16. 验收标准

1. `tests/unit/hci/test_virtual_*.py` 全部通过（VC mixin 单元，mock daemon）
2. `tests/integration/virtual_radio/test_le_scan_discovers_peer.py` 通过：peer_stack advertise，stack scan 能看到
3. `tests/integration/virtual_radio/test_le_connect_gatt.py` 通过：stack 连 peer_stack，发现 BatteryService，读出 0x180F 特性值
4. `tests/integration/virtual_radio/test_classic_inquiry_page.py` 通过：peer 启 page-scan + inquiry-scan，stack inquiry 能看到，page 能连
5. `tests/integration/virtual_radio/test_ssp_pairing.py` 通过：双方 SSP IO_Capability 交换 + User_Confirmation 完成 + 链路标记 encrypted
6. `tests/integration/virtual_radio_ipc/test_two_processes.py` 通过：起两个 pytest 子进程，跨进程 GATT 通信成功
7. `pybluehost app gatt-browser --transport=virtual` 在终端运行：内部起 peer + 真协议 discover + 打印 GATT 树
8. 跨终端 demo：Terminal 1 跑 gatt-server，Terminal 2 跑 gatt-browser，能看到 Terminal 1 起的服务
9. 全套 pytest（virtual 模式）通过；覆盖率 ≥ 85%
10. `pybluehost/transport/loopback.py` 不存在（pytest plan 已删除）；`pybluehost/cli/_loopback_peer.py` 不存在（已改名 `_virtual_peer.py`）；不再有"demo trick"代码路径
