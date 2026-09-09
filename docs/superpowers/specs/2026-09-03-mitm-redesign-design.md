# MITM 模块重构设计稿

> 状态：已确认(用户逐段对齐;2026-09-05 复审去冗)。日期：2026-09-03。
> 范围：重设计 `pybluehost/cli/app/mitm/` 的编排层，支持**同对 dongle 同时双链路(LE + BR/EDR)**;真机纪律(f382b1e / 47a8df8)、**ACL PDU 正则替换**、**scan/relay 两步式 CLI** 已并入。授权测试专用。

## 背景与动机

当前 MITM 模块的核心痛点：

1. **god-class**:`orchestrator.py` 的 `MitmRelay` 一个类 894 行(真机修复持续往里堆,f382b1e 一次 +238 行)，干了 recon 分发、impersonate 分发、LE/BR 两套 relay 装配、SMP 桥接、SSP 挂载、断链监听、连接等待(LE/BR 两套)、主动 connect、优雅断开、关 scan、teardown。
2. **LE/BR 两套平行路径**:`_build_relay` vs `_build_relay_bredr`、`_run_relay_le` vs `_run_relay_bredr`。骨架(等连接→取 buffer→建 side→注册回调→断链监听→拆链)几乎一样，唯一真差异是配对方式，却被复制成两条各 150 行的路径。
3. **`set_upstream` 全量替换的反复 hack**:每处连接等待都手写"暂存 3 个回调 → set_upstream → finally 恢复 3 个"，重复 6 处。这既是重复，也是 **both 模式 bug 的根因**(两个 relay 互相覆盖 ACL 回调)。
4. **LE 半成品**:SMP 地址是占位 `bytes(7)`(`orchestrator.py:372-375`)、没有显式 `LE_Create_Connection`、both 模式不可用。

## 设计目标(用户已确认的约束)

- **推倒重设计**编排层，但保留真机验证过的内核资产：`AclRelay` 出站解耦、`SspTermination`、controller 的 BR/EDR/LE 池分离(`hci/controller.py` 一行不动)。
- **同对 dongle 同时双链路**:downstream(面向手机)同时 LE 广播 + BR 可被扫，维持 2 条 ACL;upstream(面向耳机)同时 LE + BR 双连。
- **relay 一条命令同时拉起 LE+BR**:无需分模式跑两次;探测独立成 scan 子命令(见 CLI 使用流程)。
- **两条链路完全独立**:断链/重连互不联动(LE 断不影响 BR 音频)。
- **无多连接**:固定就 2 条链(一 LE 一 BR),不需要通用路由。

## 总体架构(最简形态)

每只 dongle 上固定 2 个 handle(LE 一个、BR 一个),建连时就知道。分发**不用路由表/总线**,就是存 4 个 handle 变量 + if/else 比较。

### 分层

```
cli.py       参数解析 + scan 列表交互 + identity JSON 读写(仍是薄 UI 层)
session.py   全部编排(替代 orchestrator.py):
               身份来源二选一:identity JSON 加载(默认)/ 内联 recon(target 匹配)
               → impersonate×(文件里有哪段就扮哪段)
               → _run_link("le") 并发 _run_link("bredr")   ← 骨架只写一遍
               → teardown
relay.py     AclRelay ×2 实例,行为原样保留;唯一新增:可选 transform 钩子(默认 None,
             不配则行为与现在逐字节一致)——见「ACL PDU 替换」节
transform.py 正则替换 demo:ReplaceRule / RegexReplacer + DEMO_RULES(用户后续自己改规则)
pairing/     ScPairing(LE)/ SspTermination(BR) 原样不动
增量:        recon.py 加 ble_scan_all(收集全部广播者)、bredr_recon.py 加 inquiry_scan_all
             (收集全部 inquiry 应答;选中后单台 RNR 补名)——现有 target 匹配函数不动,
             仍是 relay 无 identity 时的内联探测路径
不动: acl.py / capture.py / controllers.py / address.py / impersonate*.py
```

### 净效果

- `orchestrator.py`(894 行,真机修复已堆到 ~1100) → **一个 `session.py`(约 250-300 行)** + `transform.py`(约 60 行)。
- 新/改文件只有 **3 个**:`session.py`(新)、`transform.py`(新)、`cli.py`(改薄);删 `orchestrator.py`。
- 分发就是 if/else 比 2 个已知 handle,无任何路由抽象。

## MITM 三段流程(session.py 编排的流水线)

角色：手机 ⇄ **phone侧dongle**(对手机伪装成耳机) ⇄ **earbud侧dongle**(主动连真耳机) ⇄ 耳机。

1. **探测(recon)**:earbud 侧 dongle 摸真耳机的底,产物 `ClonedIdentity`(BR:BD_ADDR/CoD/EIR/名,LE:adv/scan_rsp/名)。命令行入口见下节 scan。
2. **复制(impersonate)**:phone 侧 dongle 扮成耳机(BR:CoD/EIR/名 + 开 SSP + 开 scan;LE:adv 数据 + 开广播)。
3. **中继(relay)**:两条 ACL 双向透传(详见 `_run_link` 节)。

双链路下第 1、2 段只是把"探测/复制"各跑两遍(一遍 BR 一遍 LE);第 3 段才是双链路真正的差异。

## CLI 使用流程(用户视角,两步式)

### 第 1 步:scan 探测(发现全部 → 列表选一个,结果落盘)

```
pybluehost app mitm scan --upstream usb:8087:0036#2 --mode both
# --mode: bredr→inquiry / le→adv scan / both→先 BR 后 LE
# --save 默认 mitm-targets.json,不用显式指定
```

**不指定 target**:扫出**全部**设备,编号列表让用户选一个来复制(类 TUI 选择,实现就是编号列表 + stdin 输入,不做 curses)。

- `--mode bredr`:inquiry 收集**全部**设备 → 列表(地址 / CoD / EIR 名) → 输入编号选定。EIR 拿不到名字的**只对选中的那一台**补 RNR(RNR 逐台做太慢)。
- `--mode le`:BLE adv scan 收集**全部**广播者 → 列表(地址 / 地址类型 / 名 / RSSI) → 选定。
- `--mode both`:**先 BR 后 LE,分开各自选一遍**——同一实体的 BR/LE 地址可能不同,不自动配对。
- `--target/--target-name` 保留为**可选**自动化路径(给了就直接命中不出列表;不给 = 交互式列表)。

**扫描时长与"一次没找到怎么办"**:

- 时长:BR inquiry 每轮 10.24s,默认扫 **2 轮(约 20s)** 出列表;LE adv scan 默认 **10s**。`--br-duration` / `--le-duration` 可调(自动化路径沿用 target 匹配的 90s 多轮预算,互不影响)。
- 列表下提示:`编号 选择 / r 重扫(再来一个窗口) / q 退出`——没扫到按 **r** 续一个窗口即可,不用退出重来;交互式没有总预算上限。
- 物理限制提示:设备不在可发现模式(耳机没进配对模式/没开盖)时 inquiry **本来就收不到**,重扫也没用——列表空且重扫仍空时,提示"让设备进配对模式,或改用 `--mode le`(广播通常一直在发)"。

选定后存 JSON——这是 scan↔relay 之间的桥:

```json
{
  "version": 1,
  "saved_at": "2026-09-05T04:00:00Z",
  "bredr": { "address": "38:D5:18:CD:52:F7", "name": "JBL Live Beam 4",
             "class_of_device": 9864448, "eir_hex": "..." },
  "le":    { "address": "38:D5:18:CD:52:F8", "address_type": 0,
             "name": "JBL Live Beam 4", "adv_hex": "...", "scan_rsp_hex": "..." }
}
```

JSON 里只有本次实际扫描的模式段落;relay 按**文件里有什么**就伪装什么。

**落盘按段合并**:scan 只写本次扫到的段(如 `--mode bredr` 只更新 `bredr` 键),文件里已有的其它段保留——补扫另一种链路不会抹掉已选好的设备。

relay 默认**按文件内容全跑**;`--mode le|bredr` 可只跑其中一段(如 LE 未调通时不被拖累)。

### 第 2 步:relay(日常跑,秒起)

```
pybluehost app mitm relay --upstream usb:8087:0036#2 --downstream usb:8087:0036#1
# --identity 默认 mitm-targets.json、--key-log 默认 mitm-keys.jsonl;
# 换文件/并行实验时才显式指定别的路径
```

- **默认值**:`--identity` = `mitm-targets.json`,`--key-log` = `mitm-keys.jsonl`,scan 的 `--save` 同为 `mitm-targets.json`——三处默认互相衔接,scan 完直接 relay,零参数。
- **修正现存 bug**:现在 `cli.py` 的 key-log 默认带时间戳(`mitm-<ts>-keys.jsonl`),每次重启拿到空 key 表,**重连零配对在默认参数下从未生效过**;改为固定名后跨重启生效。
- `--identity` 文件不存在且未给 `--target/--target-name` → 明确报错:"先跑 `app mitm scan`,或用 --target 指定"。
- 兼容旧用法:不给 `--identity` 但给 `--target/--target-name` → 内联探测再 relay,一条命令跑完(只有这条路径有 90s 探测等待;给了 identity 则**启动即伪装**)。

### link key / LTK 的存与用

- **BR link key(已有机制,原样保留)**:`SspTermination` 在 `Link_Key_Notification` 时追加 JSONL(`--key-log`),启动时 `_load_keys` 恢复;重连收到 `Link_Key_Request` 直接用存的 key 应答 → **重连零配对**。dongle 固件自己也存 bond,但 MITM 流程以 Host 的 JSONL 为准(应答由 Host 发)。
- **LE LTK(本次新增持久化)**:现在只存内存,进程重启就得重新 SMP 配对。同一个 JSONL 加一种记录 `{"type":"ltk","side":...,"addr":...,"ltk":...}`,session 启动时加载:手机重连发 `LE_LTK_Request` 用存的 LTK 应答;耳机侧重连后用存的 LTK 发 `LE_Start_Encryption`。
- 两侧是**两条独立配对**(手机↔dongle、耳机↔dongle 各有各的 key),JSONL 里 `side+addr` 区分,不冲突。
- 第一版限制:LTK 按地址索引,覆盖 public/static 地址;RPA(可解析随机地址)重连需要 IRK 解析,不在本次范围。

## 链路时序(LE 与 BR 同构)

**用户已确认:LE 和 BR 一致 —— 手机先连上,earbud 侧才去连真耳机**(真机 G3 实测:先连耳机会被耳机断开,因耳机不持有空闲链路)。

```
手机 page/连上 phone侧 → phone侧 accept 拿到 handle
                      → earbud侧 立即连真耳机 拿到 handle
                      → 两侧各自配对(BR:SSP产link key / LE:SMP产LTK)
                      → ACL 双向透传
```

## `_run_link` —— 一份骨架,两种模式

不抽象 `Link` 类、不定义配对插件 Protocol(就 2 条链/2 种配对,类层级和接口是过度设计)。一个函数 `_run_link(mode, accept, connect, wire_pairing)` 并发跑两次,模式差异用小参数注入。

```python
# session 启动时(等手机之前):BR 两侧 SspTermination.attach() —— 时序硬约束,见下
async def _run_link(mode, accept, connect, bring_up):
    while True:                              # 本链独立重连,不联动另一条
        phone_h   = await accept()           # 等手机连
        earbud_h  = await connect()          # 再连真耳机
        relay     = AclRelay(phone_side, earbud_side, smp_handler=smp_handler_for(mode))
        remember_handles(mode, phone_h, earbud_h)   # 供 if/else 分发用
        await bring_up(relay)                # LE:SMP 发起+LTK 加密 / BR:主动认证+加密
        await link_lost.wait()               # 常驻到本链断
        # finally: relay.stop() + 双侧优雅断开
```

**时序硬约束(G3 教训)**:BR 的 `SspTermination.attach()` 必须在 session 启动、**等手机之前**完成——手机一连上 ACL 就立即发起 SSP,迟挂必配对超时(0x13 断链)。所以 BR 的 SSP 挂载**不在** `_run_link` 里,提到 session 启动段。LE 的 `ScPairing` 是连接建立后才走 L2CAP SMP 的,可以在 `_run_link` 内建。

模式差异(注入的参数):

| 钩子 | LE | BR/EDR |
|------|-----|--------|
| `accept` | 等 `LE_Connection_Complete` | 等 `Connection_Complete`(自动 `Accept_Connection_Request`) + **连接表 tracker**(见下) |
| `connect` | `LE_Create_Connection`(**补真**) | `Create_Connection` + **查连接表复用/page 间隙采纳**(见下) |
| `bring_up`(连接后) | SMP 发起:`ScPairing` 终结 CID 0x06 产 LTK → 应答 `on_le_ltk_request` + 发 `LE_Start_Encryption` | **主动认证+加密**(见下);SSP 事件应答由启动段已挂的 `SspTermination` 承担 |

f382b1e 并入的三条 BR 真机纪律(重写时必须带进 session,不得丢):

1. **主动认证+加密**(`_secure_target_link`):relay 建立后立即 `Authentication_Requested` →(无 bond 则走 SSP 配对、key 落盘)→ `Set_Connection_Encryption`。真机实测:耳机对 AVDTP/RFCOMM 的 L2CAP 请求回 authorization-pending 等本端发起认证,无人发起则 30-60s 后 0x05 断链。旧设计稿里"经典加密随 SSP 自动协商、不强制下发"的说法**已作废**。
2. **连接表 tracker**(`addr_le_hex→handle`):耳机被手机释放后会把最近配对设备(= earbud 侧 dongle)当手机自动回连。`connect` 查表复用已存在链路 / page 间隙采纳;`accept` 对伪装身份的 page 回 `Reject(0x0D)`(那是耳机回连,不是手机来连)。
3. **prev-forward 链式 hook 被新设计收敛**:controller 有两条事件通道——(a)**内部 listener**(SSP/LTK/Encryption,`controller.py` 的 `_handle_event` 直接派发,与 `set_upstream` 无关,SspTermination 走这条);(b)唯一的 `_on_hci_event` 应用回调,**全量替换**语义。旧代码把 tracker/连接等待/断链监听全串在 (b) 上,每个 hook 都必须手工"捕获 prev 并转发",漏一处就让排在它前面的 hook 失明(f382b1e 实测)。新设计:session 是 (b) 的唯一属主,一个分发器多点订阅,不再链式 prev-forward;(a) 不受影响照常工作。

## ACL 分发(最笨的 if/else)

同一 dongle 上 LE 和 BR 的 ACL 都从同一个 `on_acl_data` 回调进来,所以要看一眼 handle 才能分——但只是跟已知的 2 个 handle 比一下,不是查表路由:

```python
# downstream(手机侧)dongle,建连时已记下 le_handle / br_handle:
def on_phone_acl(acl):
    if acl.handle == le_handle:
        le_relay.on_phone_acl(acl)      # 进 LE 这条的队列
    elif acl.handle == br_handle:
        br_relay.on_phone_acl(acl)      # 进 BR 这条的队列
    # 其它:忽略
```

upstream(耳机侧)dongle 对称一份。每个 dongle 只 `set_upstream` 一次(由 session 统一做),双链路不再互相覆盖回调——**both 模式 bug 根治**。

**两连之间的窗口**:本链"手机已连、耳机未连"的间隙里,手机先发的包(SDP 查询等)会被丢——与现状行为一致(靠对端重传,真机 5 分钟媒体流验证过),不是新引入的缺陷;若硬件回归发现 SDP 建立变慢,再考虑小缓冲暂存。

## ACL PDU 替换(正则查找→替换→转发,demo)

需求:对**特定 ACL 内容**做替换——提供正则查找、替换后转发。先给一个可用的简单 demo,**规则后续由用户自己在代码里改**。

### 作用层级:重组后的 L2CAP PDU,不是 HCI 分片

正则必须看到完整 payload 才有意义,HCI 分片边界不可控。所以在 AclRelay 内部,`reassembler.feed()` 产出完整 PDU **之后**、`encode_l2cap_basic` 重编码**之前**做替换:

- 替换导致长度变化也天然正确——`encode_l2cap_basic(cid, payload)` 按新 payload 重写 L2CAP length 头;
- 只作用于 RELAY 路径(SMP 是本地终结的,不转发也就不被替换);
- 替换发生在入队**之前**,所以 capture 抓到的就是**替换后实际上线的内容**(btsnoop 即真实);
- 代价可控:规则启动时编译一次,bytes 正则 sub 在 ≤1KB payload 上是微秒级,相对 43 帧/s 的媒体流量可忽略。

### AclRelay 的唯一改动:一个可选 transform 钩子

`AclRelay.__init__` 增加一个参数,`_handle` 里一行调用;不传(默认 None)行为与现在逐字节一致,其余逻辑(出站解耦/丢水位/抓包顺序)零改动:

```python
# transform 签名:(direction, cid, payload) -> payload。失败 fail-open:
# 抛异常则记日志、转发原帧,不杀媒体流。
PduTransform = Callable[[RelayDirection, int, bytes], bytes]
```

### transform.py:引擎 + demo 规则(约 60 行)

```python
"""ACL PDU 正则替换 demo。改规则 → 编辑本文件底部 DEMO_RULES 即可。"""
import re
from dataclasses import dataclass
from pybluehost.cli.app.mitm.acl import RelayDirection

@dataclass(frozen=True)
class ReplaceRule:
    pattern: bytes                                # bytes 正则(在 L2CAP payload 上找)
    repl: bytes                                   # 替换内容(支持 \\g<1> 反向引用)
    direction: RelayDirection | None = None       # None = 双向都替换
    cid: int | None = None                        # None = 所有 CID;指定则只替换该信道

class RegexReplacer:
    """把一组 ReplaceRule 编译成 AclRelay 的 transform 钩子。"""
    def __init__(self, rules):
        self._compiled = [(re.compile(r.pattern), r) for r in rules]
    def __call__(self, direction, cid, payload: bytes) -> bytes:
        for rx, rule in self._compiled:
            if rule.direction is not None and rule.direction is not direction:
                continue
            if rule.cid is not None and rule.cid != cid:
                continue
            payload = rx.sub(rule.repl, payload)
        return payload

# ====== DEMO:后面你自己在这里加规则 ======
DEMO_RULES = [
    # 例:把控制信道里出现的设备名字符串换掉。取消注释即生效:
    # ReplaceRule(pattern=b"WQ7035", repl=b"MITM7035"),
    # 例:只替换 phone→target 方向、且仅某个 CID 上命中 4 字节序列:
    # ReplaceRule(pattern=bytes.fromhex("deadbeef"), repl=bytes.fromhex("cafebabe"),
    #             direction=RelayDirection.PHONE_TO_TARGET),
]
```

session 构造 AclRelay 时传 `transform=RegexReplacer(DEMO_RULES)`(规则列表为空时替换是恒等,开销≈0)。暂不加 CLI 参数——用户改 `DEMO_RULES` 即可;以后要命令行注入再加 `--replace PATTERN=REPL`。

## 数据流(A2DP 音频,双链路同跑)

```
手机 --BR媒体--> [down dongle] on_phone_acl 分流→AclRelay_BR →出站队列(解耦)→分片→[up dongle]→耳机
手机 --LE控制--> [down dongle] on_phone_acl 分流→AclRelay_LE →出站队列       →[up dongle]→耳机
```

两条链各自的 AclRelay、各自的出站队列、各自的 SMP/SSP;唯一共享的是 **capture(写同一个 btsnoop)** 和 **session 的 handle 记录**。抓包仍在转发之后、后台 drain,不进转发关键路径。

## 错误处理(沿用真机纪律,不变)

- 出站解耦 + 满则丢低水位(24/4)——已在 AclRelay,两条链各自独立生效。
- 断链:本侧 `Disconnection_Complete` → **只清理本链**(relay.stop + 双侧优雅断开)→ 回本链"等手机"。另一条链不受影响。
- **每轮重连重发 `Write_Scan_Enable=0x03`**(`_ensure_phone_visible`):Intel 在 ACL 存活期间暂停 inquiry scan、断链后**不自动恢复**,不重发则第二次手机搜不到(f382b1e)。
- **recon 预算**:BR recon 是 90s 多轮重扫(47a8df8),session 编排不得用自己的短超时截断它;impersonate 已写 25ms scan activity(≈常开,治 WQ7035_MITM 搜不到/搜得慢)。
- teardown:先停两条 relay → 关 capture → 关两侧 scan → 并发 HCI_Reset 两只 dongle → 关 transport。**不带存活 ACL 退进程**(BE200 楔死教训)。
- `_graceful_disconnect` / `_disable_scan` 语义原样搬进 session。

## LE 半成品补真(重构后能做 BLE relay 测试的前提)

- 补 `LE_Create_Connection`(earbud 侧主动连真耳机)。
- 用 `LE_Connection_Complete` 事件里的**真实地址**替换 `bytes(7)` 占位(SMP f5/f6 推导需要)。
- LTK 应答 + `LE_Start_Encryption` 走通。

## 测试策略

- **守护 golden**:现有 MITM 测试文件(relay/acl/capture/controllers/pairing…,含 f382b1e 新增的 secure-target-link / conn-tracker 用例)必须继续全绿;AclRelay 除 transform 钩子外行为不变,不配 transform 时所有既有 relay 测试零改动通过。
- **新件加单测**(fake controller):
  - `_run_link` 骨架:等手机→连耳机→建 relay→记 handle(LE/BR 各一)。
  - 分发:2 个 handle 各喂 ACL,断言各进各的 relay,互不串。
  - 配对接线:LE 的 SMP 桥接双实例离线对拍(ScPairing 已支持);BR 主动认证+加密序列用 fake controller 断言命令顺序;SspTermination attach 在等手机之前(fake 断言时序)。
- **transform 单测**:规则命中替换;direction/CID 过滤;不匹配恒等返回;长度变化后 L2CAP length 头按新 payload 重写(端到端:喂 PDU→收分片重组→断言新 payload + 头);不配 transform 行为与现在一致;transform 抛异常 → 转发原帧(fail-open)。
- **scan-all 单测**:多设备 inquiry/广播各自入列表不互挤;EIR 无名选中后触发单台 RNR;身份 JSON 落盘/回读与 `ClonedIdentity` 往返一致;`--mode` 决定扫哪段、both 先 BR 后 LE。
- **重构后硬件回归**:BR/EDR 重测 5 分钟无声(golden 路径)→ 单测 LE relay → 双链路同跑。

## 硬规则(不变)

- mitm 层不 import `pybluehost.l2cap/.ble/.classic/.gap/.profiles/.stack`(只用 `hci.*` + `transport`)。
- 不改 `hci/controller.py`(BR/EDR/LE 池分离是 golden)。
- 测试用 `python -m pytest`(项目 venv 内),不用 `uv run`。
- master 不动,测试完成后才合回。
