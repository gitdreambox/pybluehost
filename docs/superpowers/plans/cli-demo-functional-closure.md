# CLI Demo 功能闭环实施计划

> **给后续 Agent/开发者**：执行本计划时，应使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按 checkbox 顺序逐步推进。

**目标**：让 CLI demo 的测试证明真实协议行为，而不是只证明命令能启动和退出。

**架构思路**：BLE peripheral demo 复用现有 GAP advertiser、ATT fixed channel 绑定、GATT server 和 BLE profile decorators。Classic SDP/SPP demo 不能隐藏底层缺失；在 Classic ACL、L2CAP dynamic PSM、SDPClient、RFCOMM session state machine 完成前，必须显式暴露未实现路径。

**技术栈**：Python 3.10+、asyncio、pytest、pybluehost HCI/L2CAP/GATT/RFCOMM 模块。

---

### Task 1：BLE GATT Callback 绑定

**文件：**
- 修改：`pybluehost/ble/gatt.py`
- 修改：`pybluehost/profiles/ble/base.py`
- 修改：`pybluehost/profiles/ble/bas.py`
- 修改：`pybluehost/profiles/ble/hrs.py`
- 测试：`tests/unit/ble/test_gatt.py`
- 测试：`tests/unit/profiles/test_builtin.py`

- [x] **Step 1：新增会失败的 GATT read/write callback 测试**

运行：

```bash
uv run --frozen pytest tests/unit/ble/test_gatt.py::test_gatt_server_read_request_uses_bound_handler tests/unit/ble/test_gatt.py::test_gatt_server_write_request_uses_bound_handler -q --transport=virtual
```

实现前预期：FAIL，因为 `GATTServer.register_read_handler()` 和 `register_write_handler()` 不存在。

- [x] **Step 2：把 profile callback 绑定到 GATTServer**

`BLEProfileServer.register()` 将 `@on_read`、`@on_write`、`@on_notify` 方法绑定到对应 characteristic value handle。

- [x] **Step 3：profile 状态变化同步到 GATT DB**

`BatteryServer.update_level()` 和 `HeartRateServer.update_measurement()` 会刷新 characteristic value，并对已订阅连接发送 notification。

- [x] **Step 4：验证 profile 测试通过**

运行：

```bash
uv run --frozen pytest tests/unit/ble/test_gatt.py tests/unit/profiles/test_builtin.py -q --transport=virtual
```

预期：PASS。

### Task 2：BLE Peripheral CLI 广播

**文件：**
- 新建：`pybluehost/cli/app/_ble_peripheral.py`
- 修改：`pybluehost/cli/app/gatt_server.py`
- 修改：`pybluehost/cli/app/hr_monitor.py`
- 修改：`pybluehost/ble/gap.py`
- 测试：`tests/unit/cli/test_app_gatt_server.py`
- 测试：`tests/unit/cli/test_app_hr_monitor.py`
- 测试：`tests/unit/ble/test_gap.py`

- [x] **Step 1：新增 connectable advertising 行为测试**

测试断言 `BLEAdvertiser.start()` 被调用，参数包含 ADV_IND、flags、service UUID、scan response name，并且退出时调用 `stop()`。

- [x] **Step 2：新增共享 BLE 广播 helper**

`_ble_peripheral.py` 负责构造 AD flags、UUID16 service list、scan response local name，并启动/停止 connectable advertising。

- [x] **Step 3：发送 scan response data**

`BLEAdvertiser.start()` 在 enable advertising 前发送 `HCI_LE_Set_Scan_Response_Data`。

- [x] **Step 4：验证 BLE app 测试通过**

运行：

```bash
uv run --frozen pytest tests/unit/cli/test_app_gatt_server.py tests/unit/cli/test_app_hr_monitor.py tests/unit/ble/test_gap.py -q --transport=virtual
```

预期：PASS。

### Task 3：Classic Demo Stub 显式暴露

**文件：**
- 修改：`pybluehost/classic/rfcomm.py`
- 修改：`pybluehost/cli/app/spp_echo.py`
- 测试：`tests/unit/classic/test_rfcomm.py`
- 测试：`tests/unit/cli/test_app_spp_echo.py`

- [x] **Step 1：让 RFCOMM no-op 方法显式失败**

`RFCOMMManager.listen()` 和没有 L2CAP 支撑的 channel 操作抛出 `NotImplementedError`，不再静默成功。

- [x] **Step 2：保留可测试的 RFCOMM frame 输出**

当存在 L2CAP-backed session 时，`RFCOMMChannel.send()` 会按 `max_frame_size` 分片并写出 UIH frames。

- [x] **Step 3：让 spp-echo 走 SPPService**

CLI 注册 SDP record 并调用 RFCOMM listen。在 Classic L2CAP PSM `0x0003` 实现前，它会报告真实缺失层。

- [x] **Step 4：验证 Classic stub 暴露测试通过**

运行：

```bash
uv run --frozen pytest tests/unit/classic/test_rfcomm.py tests/unit/cli/test_app_spp_echo.py -q --transport=virtual
```

预期：PASS，且测试明确断言缺失的是 Classic L2CAP/RFCOMM 路径。

### Task 4：剩余 Classic 真实链路

**文件：**
- 后续修改：`pybluehost/classic/gap.py`
- 后续修改：`pybluehost/l2cap/classic.py`
- 后续修改：`pybluehost/l2cap/manager.py`
- 后续修改：`pybluehost/classic/sdp.py`
- 后续修改：`pybluehost/classic/rfcomm.py`
- 后续修改：`pybluehost/cli/app/sdp_browser.py`
- 后续修改：`pybluehost/cli/app/spp_echo.py`

- [x] **Step 1：实现 BR/EDR ACL connection waiter**

提供类似 `Stack.connect_gatt()` 的 app-level Classic ACL handle 获取 API。

- [x] **Step 2：实现 Classic L2CAP dynamic PSM connect/listen**

已完成 outgoing connect 与 incoming listen/accept 路径，支持连接和监听 SDP PSM `0x0001`、RFCOMM PSM `0x0003`。

- [x] **Step 3：实现基于 L2CAP 的 SDPClient**

`sdp-browser` 必须发送真实 ServiceSearchAttribute request，并打印远端 SDP records。

- [x] **Step 4：实现 RFCOMM session state machine**

已完成 outgoing SABM/UA multiplexer + DLC 打开、server-side incoming SABM/UA、UIH data dispatch、`SPPClient.connect()` 与 `spp_echo` listen 注册路径。

- [ ] **Step 5：新增 CSR 硬件验收**

使用：

```bash
uv run pybluehost app sdp-browser -t usb:vendor=csr -a A0:90:B5:10:40:82
uv run pybluehost app spp-echo -t usb:vendor=csr
```

实现后预期：不再出现 `NotImplementedError`，并且 HCI/btsnoop trace 能看到真实协议流量。

2026-04-28 当前验收状态：
- `sdp-browser` 已经走到 Classic ACL Create Connection，失败点为目标设备 paging 返回 `PAGE_TIMEOUT (0x04)`，不是 SDP/RFCOMM stub。
- `spp-echo` 首次受控启动没有立即退出；随后 CSR8510 被系统拒绝访问，`pybluehost tools usb diagnose` 显示 `0a12:0001` 为 `Access denied` / `DRIVER_CONFLICT`，因此 CSR app 级验收未完成。
- 保持本 Step 未勾选；需要恢复 CSR WinUSB/设备占用状态后重跑。

---

## 本计划新增测试策略

- CLI demo 测试必须至少断言一个协议侧效果：HCI command、ATT PDU、SDP record、RFCOMM frame，或应用层可见的连接/错误事件。
- 只验证 CLI coroutine 能 start/stop 的测试，不足以证明 demo 可用。
- 未完成的协议路径必须显式抛出 `NotImplementedError`，并在测试中写清楚缺失的是哪个下层能力。
- 硬件验证必须使用确定性 transport，例如 `--transport usb:vendor=csr`。
