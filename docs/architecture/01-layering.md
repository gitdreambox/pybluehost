# 第一节：整体分层与模块边界

## 1.1 层次结构

```
┌─────────────────────────────────────────────────────────────┐
│                     应用 / 用户代码                           │
├─────────────────────────────────────────────────────────────┤
│                    profiles/                                 │
│  ble/hrs.py  ble/bas.py  ble/hids.py  classic/spp.py  …    │
├──────────────────────┬──────────────────────────────────────┤
│     ble/             │           classic/                   │
│  att.py  gatt.py     │     sdp.py   rfcomm.py              │
│  smp.py  gap_le.py   │     gap_classic.py                  │
├──────────────────────┴──────────────────────────────────────┤
│                      l2cap/                                  │
│   channel.py（抽象）  ble.py   classic.py   signaling.py    │
├─────────────────────────────────────────────────────────────┤
│                       hci/                                   │
│   packets.py   controller.py   flow.py   virtual.py         │
├─────────────────────────────────────────────────────────────┤
│                    transport/                                │
│   base.py  uart.py  usb.py  tcp.py  udp.py                 │
│   loopback.py  btsnoop.py                                   │
├─────────────────────────────────────────────────────────────┤
│                   core/（共享基础）                           │
│   statemachine.py  trace.py  errors.py  buffer.py           │
│   address.py  uuid.py  keys.py                              │
└─────────────────────────────────────────────────────────────┘
```

## 1.2 包结构

```
pybluehost/
├── __init__.py
├── stack.py                  # Stack 工厂，顶层组装入口
├── core/                     # 共享基础设施，无蓝牙业务逻辑
│   ├── statemachine.py
│   ├── trace.py
│   ├── errors.py
│   ├── buffer.py             # PDU 构造/解析辅助
│   ├── address.py            # BDAddress, AddressType（全栈唯一定义）
│   ├── uuid.py               # UUID16 / UUID128，常量库
│   ├── keys.py               # LinkKey / LTK / IRK 数据类
│   ├── types.py              # IOCapability, ConnectionRole, LinkType 等跨层共享枚举
│   ├── gap_common.py         # ClassOfDevice, ServiceClass, Appearance 等 GAP 特有类型
│   └── sig_db.py             # SIG 官方 YAML 数据查表（UUID/Company ID/常量）
├── transport/
│   ├── base.py               # Transport ABC + AsyncTransport mixin
│   ├── uart.py               # H4 framing over serial
│   ├── usb.py                # USB / WinUSB via pyusb，含芯片自动识别和固件加载
│   ├── tcp.py
│   ├── udp.py
│   ├── loopback.py
│   └── btsnoop.py            # 读写 btsnoop，也可作 transport 回放
├── hci/
│   ├── packets.py            # 所有 HCI packet encode/decode
│   ├── constants.py          # Opcode、Event Code、Error Code、OGF/OCF 常量
│   ├── controller.py         # HCI 层主逻辑，flow control，状态机
│   ├── flow.py               # Host_Num_Completed_Packets，command credit
│   ├── virtual.py            # VirtualController
│   └── vendor/
│       ├── intel.py           # Intel vendor command/event 定义
│       └── realtek.py         # Realtek vendor command/event 定义
├── l2cap/
│   ├── channel.py            # Channel ABC（上层统一接口）
│   ├── manager.py            # L2CAPManager 主类
│   ├── ble.py                # BLE L2CAP（fixed channels + CoC）
│   ├── classic.py            # Classic L2CAP（ERTM/Streaming/Basic）
│   ├── signaling.py          # L2CAP signaling channel 处理
│   ├── sar.py                # 分段重组引擎
│   └── constants.py          # CID 常量、PSM
├── ble/
│   ├── att.py
│   ├── gatt.py
│   ├── smp.py
│   └── gap.py
├── classic/
│   ├── sdp.py
│   ├── rfcomm.py
│   ├── spp.py
│   └── gap.py
├── lib/
│   └── sig/                  # git submodule（SIG 官方 YAML 数据）
└── profiles/
    ├── ble/
    │   ├── base.py            # BLEProfileServer / BLEProfileClient 基类
    │   ├── yaml_loader.py     # YAML Service 定义加载器
    │   ├── decorators.py      # @ble_service / @on_read / @on_write / @on_notify
    │   ├── services/          # 内置 Service 定义（YAML）
    │   │   ├── gap.yaml  gatt.yaml  dis.yaml  bas.yaml  hrs.yaml
    │   │   ├── bls.yaml  hids.yaml  rscs.yaml  cscs.yaml
    │   ├── gap_service.py  gatt_service.py
    │   ├── dis.py  bas.py  hrs.py  bls.py
    │   ├── hids.py  rscs.py  cscs.py
    └── classic/
        └── spp.py
```

## 1.3 层间依赖规则

- 每层**只能向下依赖**，不得向上调用
- 层间通过 **SAP 接口**通信，不得直接访问对方内部属性
- `core/` 可被任何层引用，自身不依赖任何协议层
- `profiles/` 只依赖 `ble/` 或 `classic/`，不直接操作 `hci/` 或 `transport/`
- `stack.py` 是唯一允许跨层组装的地方
