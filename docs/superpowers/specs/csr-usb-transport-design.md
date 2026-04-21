# CSR USB Transport 设计

日期：2026-04-21
主题：为 CSR8510（`0x0A12:0x0001`）增加 CSR USB Transport 支持

## 背景

当前 `pybluehost.transport.usb` 已经能够识别 Intel 和 Realtek 的 USB 蓝牙芯片，并在需要固件加载或厂商初始化时分流到各自的 Transport 子类。

当前测试环境中存在一块 CSR8510 USB 适配器，Windows 识别名称为 `CSR8510 A10`，其关键 USB 描述符信息如下：

- VID/PID：`0x0A12:0x0001`
- 设备类：`0xE0/0x01/0x01`（Bluetooth Wireless Controller）
- Interface 0 端点：
  - Interrupt IN `0x81`
  - Bulk OUT `0x02`
  - Bulk IN `0x82`

这组描述符与现有 `USBTransport.open()` 的接口和端点发现逻辑完全兼容。

## 目标

为 CSR USB 适配器增加一等识别能力，使 `USBTransport.auto_detect()` 在检测到 `0x0A12:0x0001` 时返回 CSR 专属 Transport 类型，同时保持实现尽量小、尽量贴合现有结构。

## 非目标

- 不实现 CSR 私有固件下载
- 不实现 CSR 私有 bootstrap、patchram 或厂商命令初始化流程
- 不增加 SCO / isochronous 数据通路支持
- 本次不扩展到所有可能的 CSR VID/PID 组合

## 方案比较

### 方案一：将 CSR8510 直接映射到通用 `USBTransport`

优点：

- 改动最小
- 不需要新增子类

缺点：

- 检测成功后丢失了厂商和类型语义
- 未来如果要加 CSR 专有逻辑，扩展点不够清晰
- 与 Intel / Realtek 的建模方式不一致

### 方案二：新增一个轻量的 `CSRUSBTransport`

优点：

- 实现很小，但保留了明确的厂商身份
- 为以后增加 CSR 专有逻辑预留了自然扩展点
- 与 `KNOWN_CHIPS` 当前的建模方式保持一致

缺点：

- 会增加一个当前暂时没有特殊初始化逻辑的子类

### 方案三：新增 `CSRUSBTransport`，并尝试加入推测性的厂商初始化

优点：

- 可以更早为 CSR 深度支持做铺垫

缺点：

- 在缺少确认过的 CSR 命令序列前提下风险较高
- 容易把当前已经可用的通用 HCI 路径做坏
- 现阶段难以在项目内充分验证

## 结论

选择方案二。

新增一个轻量的 `CSRUSBTransport`，继承 `USBTransport`，默认沿用基类的 no-op 初始化逻辑；同时将 CSR8510 注册进 `KNOWN_CHIPS`。

## 设计

### Transport 模型

新增：

- `CSRUSBTransport(USBTransport)`

行为：

- 复用 `USBTransport.open()`、端点发现、control / bulk 路由和关闭逻辑
- `_initialize()` 继续沿用基类默认的 no-op 行为
- 通过现有 `TransportInfo` 输出 vendor / name 信息

### 设备注册表

在 `KNOWN_CHIPS` 中新增：

- `ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport)`

这里的 `firmware_pattern` 当前不会被使用，因为本次不实现 CSR 固件加载。保留空字符串即可，前提是 CSR 子类继续走无固件初始化路径。

### 公共导出

更新 `pybluehost.transport.__init__`，导出 `CSRUSBTransport`，方便上层直接导入、类型判断或显式实例化。

### 测试策略

补充测试，验证以下行为：

- `KNOWN_CHIPS` 中包含 CSR8510
- `USBTransport.auto_detect()` 在 `0x0A12:0x0001` 上返回 `CSRUSBTransport`
- `CSRUSBTransport` 是 `USBTransport` 的子类
- 现有 Intel / Realtek 的检测路径不受影响

按 TDD 执行：

1. 先添加 CSR 注册和检测相关的失败测试
2. 运行聚焦的 USB transport 测试，确认先红
3. 再补最小实现
4. 重新运行测试直到转绿
5. 最后跑覆盖 USB 行为的 transport 测试子集

### 硬件冒烟验证

在单元测试通过后，使用本机 CSR8510 做一轮最小硬件验证：

- 确认 `USBTransport.auto_detect()` 返回 `CSRUSBTransport`
- 确认设备可以成功 `open()` / `close()`，且端点发现阶段不报错

如果因为 backend 或环境限制导致无法完成打开验证，则保留代码变更，同时明确记录硬件验证缺口。

## 风险

### 某些 CSR 适配器可能需要厂商专有初始化

缓解方式：

- 本次支持范围明确限定为 CSR8510 `0x0A12:0x0001`
- 保留 `CSRUSBTransport` 子类边界，后续需要扩展时无需重新设计整体结构

### 空的 `firmware_pattern` 未来可能被误用

缓解方式：

- 保持 CSR 初始化走基类 no-op 路径
- 在代码注释中明确说明当前不支持 CSR 固件加载

## 完成标准

- `USBTransport.auto_detect()` 能识别 CSR8510
- 检测结果是 `CSRUSBTransport`，而不是通用 `USBTransport`
- USB transport 相关单元测试通过
- 本机最小 open / close 冒烟验证通过，或明确记录阻塞原因
