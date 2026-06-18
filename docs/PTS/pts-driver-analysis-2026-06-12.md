# Intel Bluetooth PTS 驱动分析

日期：2026-06-12

分析根目录：`PTS Driver/`

## 分析范围

本文比较以下三个目录中的驱动包：

- `ibtusb/`
- `MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS/`
- `SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/`

同时分析两个问题：

- `MHBTW` 包中面向 PID0041 的 PTS 驱动能否强行安装到 PID0036 设备上。
- `ibtusb.sys` / `ibtusbpts.sys` 中嵌入的固件 blob 差异，以及可提取的 `.sfi`、`.bseq` 文件。

## 结论摘要

对 `USB\VID_8087&PID_0036` 设备，最合适的 PTS 驱动是：

`SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/FRE/IntelPTS/USB/GAP/x64/`

不建议直接使用：

`MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS/FRE/IntelPTS/USB/GAP_CERT/x64/`

原因是 `MHBTW ... GAP_CERT` 包里的 `ibtusbpts.inf` 只声明了：

- `USB\VID_8087&PID_0041&REV_0000`
- `USB\VID_8087&PID_0041&REV_0001`

它没有声明 `USB\VID_8087&PID_0036`，所以 Windows 不会自然把它绑定到 PID0036 设备。修改 INF 添加 PID0036 会破坏原始 `ibtusbpts.cat` 目录签名，需要重新签名、测试签名模式，或禁用签名强制策略。即便强行安装成功，该驱动内部组件标记是 `GAP_CERT`，固件集合也和 PID0036 的 `GAP` 包不同，可能出现固件下载失败、固件校验失败或 PTS 行为异常。

已从 SYS 文件中提取到固件类 blob。实际找到并导出的升级 payload 是 `.sfi` 和 `.bseq`。没有发现独立命名的 `.dcc` / `.ddc` 固件资源；SYS 中只有 DDC 相关命令和配置字符串。

固件导出目录：

`extracted_firmware_from_sys/`

## 驱动包对比

### 1. `ibtusb/`

`ibtusb/` 目录下是普通 Intel Bluetooth 类驱动，不是 PTS WinUSB 驱动。各子目录通常包含：

- `ibtusb.inf`
- `ibtusb.cat`
- `ibtusb.sys`

关键属性：

- INF 类：`Bluetooth`
- Class GUID：`{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}`
- 服务名：`ibtusb`
- 服务文件：`%13%\ibtusb.sys`
- 已检查的 `GAP` 包驱动版本：`03/28/2026,24.40.0.3`
- 签名方：`Microsoft Windows Hardware Compatibility Publisher`

观察到的 PID 映射：

| 子目录 | PID |
|---|---|
| `GAP` | `USB\VID_8087&PID_0036&REV_0000`、`REV_0001` |
| `FMP` | `PID_0037` |
| `MTP` | `PID_0038` |
| `GFP` | `PID_0033` |
| `HRP` | `PID_0026` |
| `JFP` | `PID_0AAA` |
| `THP` | `PID_0025` |
| `TYP` | `PID_0032` |

`ibtusb/GAP/` 是 PID0036 的普通 Windows 蓝牙栈驱动。它会让设备作为 Bluetooth Radio 出现在系统中，而不是作为 PTS WinUSB Adapter。

### 2. `MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS/`

实际存在的驱动目录：

`MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS/FRE/IntelPTS/USB/GAP_CERT/x64/`

文件：

| 文件 | 大小 | SHA256 |
|---|---:|---|
| `ibtusbpts.inf` | 36,712 | `E773259DE2CD5C0A559C7F5BA6992DAF5B315A428A3FA90E023892140D247181` |
| `ibtusbpts.cat` | 11,944 | `803E138B0C1D0AED48ED8E881D101EDE2828AFFA839698DC3C68CD36DFA8E93A` |
| `ibtusbpts.sys` | 3,757,112 | `1A3E7E624FA46B550A5F4B0A0A67C15E38F8D591E8F15C5F2F4ABF5FCC52A959` |

INF 属性：

- INF 类：`USBDevice`
- Class GUID：`{88BAE032-5A81-49f0-BC3D-A4FF138216D6}`
- 服务名：`ibtusbpts`
- 服务文件：`%13%\ibtusbpts.sys`
- 驱动版本：`11/19/2025,24.20.25473.23919`
- 声明的硬件 ID：
  - `USB\VID_8087&PID_0041&REV_0000`
  - `USB\VID_8087&PID_0041&REV_0001`
- SYS 内部包标记：`MHBTW_AT_PTS_REL23919`
- SYS 内部组件标记：`GAP_CERT`
- SYS 内部认证标记：`Attestation_PTS`
- 签名状态：有效

需要注意的矛盾点：

该包的 `Manifest.json` 中列出了多个 build component，其中包括 `GAP` 组件，且该组件对应 `USB\VID_8087&PID_0036`。但是当前目录树里实际解压出来并可用的是 `GAP_CERT` 目录，该目录中的 INF 只面向 PID0041。换句话说，当前分析树里没有 `MHBTW` 包的 PID0036 `GAP` 独立驱动目录。

### 3. `SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/`

实际驱动目录：

`SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/FRE/IntelPTS/USB/GAP/x64/`

文件：

| 文件 | 大小 | SHA256 |
|---|---:|---|
| `ibtusbpts.inf` | 36,712 | `261D3E048127BACE4CDB34B1D7CBB9AAAD5913251E064AC8D4A877A0827195C3` |
| `ibtusbpts.cat` | 11,798 | `E73A0966721882B983064BE6B513A94C11C86F5F9D3617104430252BD0879280` |
| `ibtusbpts.sys` | 7,334,592 | `86F393D0BC787B7F78666C999FEE9911247F1A36C075759289866E7270181616` |

INF 属性：

- INF 类：`USBDevice`
- Class GUID：`{88BAE032-5A81-49f0-BC3D-A4FF138216D6}`
- 服务名：`ibtusbpts`
- 服务文件：`%13%\ibtusbpts.sys`
- 驱动版本：`06/12/2024,23.80.24243.43500`
- 声明的硬件 ID：
  - `USB\VID_8087&PID_0036&REV_0000`
  - `USB\VID_8087&PID_0036&REV_0001`
- SYS 内部包标记：`SBHBTW_AT_PTS_REL43500`
- SYS 内部组件标记：`GAP`
- SYS 内部认证标记：`Attestation_PTS`
- 签名状态：有效

这是当前目录中明确匹配 PID0036 的签名 PTS WinUSB 驱动。

## 能否把 MHBTW PID0041 驱动强行安装到 PID0036？

简短结论：不能用原始签名包干净安装；可以通过修改 INF + 测试签名实验，但不推荐作为正常方案。

详细分析：

1. Windows 驱动匹配基于 INF 中声明的硬件 ID。
2. `MHBTW.../GAP_CERT/x64/ibtusbpts.inf` 只声明 PID0041。
3. PID0036 设备不会匹配这个 INF，因此 `pnputil /add-driver ... /install` 只会把驱动包加入驱动仓库，不会把它绑定到 PID0036。
4. 通过 Windows 驱动更新 API 强制指定 INF 时，仍然要求 INF 中存在兼容硬件 ID。没有 PID0036 匹配项时，绑定会失败或被拒绝。
5. 修改 INF 添加 `USB\VID_8087&PID_0036&REV_0000` / `REV_0001` 会导致 `ibtusbpts.cat` 中记录的文件哈希失效。
6. CAT 哈希失效后，普通 Windows 内核驱动签名策略会阻止该包安装或加载，除非重新签名并开启测试签名，或禁用签名强制策略。
7. 即使在测试签名环境中强行安装成功，SYS 内部元数据仍标记为 `GAP_CERT`，固件集合也不同于 PID0036 的 `GAP` 包。结果可能是固件验证失败、固件下载失败、PTS 无法识别设备，或 HCI 行为异常。

建议：

PID0036 的 PTS 工作应优先使用：

`SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/FRE/IntelPTS/USB/GAP/x64/`

除非目标就是在隔离测试环境中验证失败行为，否则不建议把当前可用的 `MHBTW.../GAP_CERT/` PID0041 包强行安装到 PID0036。

## SYS 二进制差异

### 大小和版本标记

| 包 | SYS | 大小 | 版本标记 | Build 标记 | 组件标记 |
|---|---|---:|---|---|---|
| `ibtusb/GAP` | `ibtusb.sys` | 3,745,224 | `24.40.0.3` | `MHBTW_PP_REL36423` | `GAP` |
| `MHBTW GAP_CERT` | `ibtusbpts.sys` | 3,757,112 | `24.20.25473.23919` | `MHBTW_AT_PTS_REL23919` | `GAP_CERT` |
| `SBHBTW GAP` | `ibtusbpts.sys` | 7,334,592 | `23.80.24243.43500` | `SBHBTW_AT_PTS_REL43500` | `GAP` |

### PE Section 布局

关键差异在 `.data` 节。该节体积大、熵值高，承载了嵌入的固件/配置 blob。

| 包 | `.text` raw | `.rdata` raw | `.data` raw | `.data` 熵值 |
|---|---:|---:|---:|---:|
| `ibtusb/GAP` | `0xD1E00` | `0x5C00` | `0x2AA400` | 7.10 |
| `MHBTW GAP_CERT` | `0xCEE00` | `0x5A00` | `0x2B0200` | 7.11 |
| `SBHBTW GAP` | `0xB3400` | `0x5A00` | `0x636E00` | 7.11 |

`SBHBTW GAP` 明显更大，原因是内嵌了更多固件变体：

- `SBHBTW`：5 个 `bseq_*` blob + 7 个 `sfi_*` blob
- `MHBTW GAP_CERT`：2 个 `bseq_*` blob + 4 个 `sfi_*` blob
- `ibtusb GAP`：2 个 `bseq_*` blob + 4 个 `sfi_*` blob

### PTS 驱动与普通驱动的区别

`ibtusb.sys`：

- 普通 Bluetooth 类驱动
- INF 类是 `Bluetooth`
- 服务名是 `ibtusb`
- Windows 蓝牙栈拥有并管理该 radio

`ibtusbpts.sys`：

- PTS adapter 驱动
- INF 类是 `USBDevice`
- 服务名是 `ibtusbpts`
- 面向 PTS 使用 WinUSB 风格访问
- 设备显示为 `Intel(R) Bluetooth(R) PTS Adapter`

## 提取出的固件 Blob

导出根目录：

`extracted_firmware_from_sys/`

提取脚本在 SYS 中找到了固件表：

- 第一个指针指向 `.data` 中的 blob
- 第二个指针指向 `.rdata` 中的固件名字符串

PE 资源目录中没有命名的固件资源。这些 blob 是以静态数据形式编进 SYS 的，不是普通 Win32 resource。

### 从 `ibtusb/GAP/Win10_UWDRelease/x64/ibtusb.sys` 提取

输出目录：

`extracted_firmware_from_sys/ibtusb_gap_24.40.0.3/`

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 32 | `04AAFAAD192E8CCA` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 991,856 | `AA44ED336570FAC7` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 495,591 | `23D6DC0D73127818` |
| `sfi_BLAZARU_A0_FMPC0_LC3.sfi` | 75,984 | `1A0B515EC5DCDD60` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 932,280 | `F0A83912A31369F4` |

### 从 `MHBTW.../GAP_CERT/x64/ibtusbpts.sys` 提取

输出目录：

`extracted_firmware_from_sys/mh_gap_cert_pts_24.20.25473.23919_pid0041/`

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 32 | `04AAFAAD192E8CCA` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 990,064 | `C81C309BC2814103` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 509,671 | `D866CAC10308EC37` |
| `sfi_BLAZARU_A0_FMPC0_LC3.sfi` | 75,984 | `77DCB93213E66658` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 960,448 | `B4A583EEE9AF73F5` |

### 从 `SBHBTW.../GAP/x64/ibtusbpts.sys` 提取

输出目录：

`extracted_firmware_from_sys/sbh_gap_pts_23.80.24243.43500_pid0036/`

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_FMP_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_WHP_STC.bseq` | 22 | `726B8A827EBCFDC2` |
| `sfi_BLAZARU_A0.sfi` | 905,480 | `86FBD725B3CE169A` |
| `sfi_BLAZARU_A0_FMP_A0.sfi` | 704,775 | `6D858465A4C17614` |
| `sfi_BLAZARU_A0_FMP_A0_REDUCED.sfi` | 842,512 | `81955A0EDD96DE70` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 978,688 | `95B30088980C8497` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 842,576 | `8DED88A2A4C20CB9` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 969,792 | `62D2C260BB8FC678` |
| `sfi_BLAZARU_A0_WHP_STC.sfi` | 991,984 | `6686DCD5B890C7AB` |

每个输出目录中还有 `manifest.json`，记录了文件偏移、虚拟地址、大小、SHA256 和头部字节。

## 关于 `.dcc` / `.ddc`

没有在 PE 资源表或固件指针表中发现独立的 `.dcc` / `.ddc` 固件文件。

驱动中确实包含 DDC 相关字符串，例如：

- `DDC_READ_REQ`
- `DDC_READ_RSP`
- `DDC_WRITE_INTEL_MSFT_FEATURE_MASK_CMD`
- `TX_PWR_DDC_CMD`
- `ANT_DIV_DDC_CMD`

这些更像是驱动内部命令/配置标签，不是可直接导出的独立 DDC 固件文件。当前这些 SYS 文件中实际可提取的升级 payload 是 `.sfi` 和 `.bseq`。

## `ibtusbpts.sys` 如何选择加载哪个 SFI

SYS 中同时内置多个 `.sfi`，但驱动不是按 USB PID 直接挑选固件。`PID_0036` / `PID_0041` 的主要作用是让 Windows PnP 选择并绑定哪个驱动包；驱动真正进入启动流程后，会先和控制器通信，再根据控制器返回的 Intel vendor 版本/TLV 信息选择固件。

从 `ibtusbpts.sys` 字符串和固件表可以看到以下线索：

- `Lookup Version:`
- `Found Version:`
- `FW Build Version:`
- `Tlv Fw Read Version`
- `Bootloader`
- `Operational`
- `Legacy(ROM)`
- `Modern(RAM)`
- `FwDownloadSFI failed`
- `FW Download failed - FW Not Found`
- `FW Validation failed`

因此实际选择链路应为：

1. Windows 通过 INF/PID 加载 `ibtusbpts.sys`。
2. 驱动判断控制器当前处于 `Bootloader` 还是 `Operational`。
3. 驱动发送 Intel vendor HCI 命令读取控制器版本/TLV。
4. 控制器返回平台、硬件变体、硬件 revision、固件状态等信息。
5. 驱动把这些字段映射为内部固件名，例如 `BLAZARU_A0_FMP_C0`、`BLAZARU_A0_WHP_A0`、`BLAZARU_A0_WHP_STC`。
6. 驱动在 SYS 内部固件表中查找对应的 `sfi_*` 和 `bseq_*`。
7. 驱动下载 `.sfi`，触发控制器 reset 进入 operational firmware。
8. 驱动继续加载对应 `.bseq` / DDC 类配置。

后缀含义基于当前样本推断如下：

| 后缀 | 含义推断 |
|---|---|
| `BLAZARU_A0` | 平台 / silicon stepping 基础名 |
| `FMP_A0`、`FMP_C0` | FMP 子平台或 CNV/RF 变体及 revision |
| `WHP_A0`、`WHP_STC` | WHP 子平台或 CNV/RF 变体 |
| `REDUCED` | 裁剪/恢复/受限下载路径使用的固件变体 |
| `LC3` | 带 LC3 或音频能力相关的固件变体 |

这解释了强行安装 `MHBTW ... GAP_CERT` 到 PID0036 后出现 Code 10 的原因：INF 匹配可以被修改，但控制器返回的硬件变体不会随 INF 改变。如果 PID0036 设备需要 `BLAZARU_A0`、`FMP_A0` 或 `WHP_STC` 这类固件，而 `GAP_CERT` 包中没有对应 SFI，驱动会进入 `FW Download failed - FW Not Found` 或 `FW Validation failed` 路径。即使名称匹配，`GAP_CERT` 的认证用途固件也可能因为校验策略或组件标记不同而失败。

## 固件提取脚本

已新增脚本：

`scripts/extract_ibtusb_firmware.py`

脚本使用 Python 标准库完成以下工作：

1. 解析 PE section 和 image base。
2. 扫描 `sfi_*` / `bseq_*` ASCII 固件名。
3. 查找 SYS 内部 `<blob_va, name_va>` 指针表。
4. 将 VA 映射回文件偏移。
5. 对 `.sfi` 使用 Intel SFI 头部长度字段和 16 字节对齐确定边界。
6. 对 `.bseq` 使用 HCI 命令/事件片段长度确定边界，避免把纯填充误认为固件内容。
7. 导出固件文件和 `manifest.json`，记录偏移、VA、大小、SHA256 和头部字节。

示例：

```powershell
python scripts\extract_ibtusb_firmware.py `
  -o extracted_firmware_from_sys `
  "PTS Driver\ibtusb\GAP\Win10_UWDRelease\x64\ibtusb.sys" `
  "PTS Driver\MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS\FRE\IntelPTS\USB\GAP_CERT\x64\ibtusbpts.sys" `
  "PTS Driver\SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2\FRE\IntelPTS\USB\GAP\x64\ibtusbpts.sys"
```

只查看 manifest、不写出固件：

```powershell
python scripts\extract_ibtusb_firmware.py --manifest-only "PTS Driver\...\ibtusbpts.sys"
```

### 脚本自测结果

自测输出目录：

`.temp/ibtusb_extract_selftest/`

自测命令覆盖三份 SYS：

- `ibtusb/GAP/Win10_UWDRelease/x64/ibtusb.sys`
- `MHBTW_AT_PTS_REL23919_24.20.25473.23919PTS/FRE/IntelPTS/USB/GAP_CERT/x64/ibtusbpts.sys`
- `SBHBTW_AT_PTS_REL43500_23.80.24243.43500PTS 2/FRE/IntelPTS/USB/GAP/x64/ibtusbpts.sys`

自测检查项：

- manifest 记录数与导出文件数一致。
- 导出文件大小与 manifest 中 `size` 一致。
- 导出文件 SHA256 与 manifest 中 `sha256` 一致。
- `.sfi` 文件头为 `06000000a1000000`。
- `.bseq` 文件头为 `018b`。

结果：

| SYS | 提取数量 | 总大小 |
|---|---:|---:|
| `ibtusb/GAP` | 6 | 2,789,762 |
| `MHBTW GAP_CERT` | 6 | 2,814,070 |
| `SBHBTW GAP` | 12 | 6,509,758 |

脚本口径会修正早期手工扫描结果中的个别长度偏差：早期结果有些 SFI 按扫描截断或包含不同填充口径；当前脚本以 SFI 头部长度字段、后继固件指针和 16 字节对齐为准。BSEQ 当前按可解析 HCI 片段长度导出，不把尾部纯 `00` 填充计入固件。

按脚本口径得到的清单如下。

### 从 `ibtusb/GAP/Win10_UWDRelease/x64/ibtusb.sys` 提取

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 991,856 | `AA44ED336570FAC7` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 789,616 | `B13674377FEAD1A7` |
| `sfi_BLAZARU_A0_FMPC0_LC3.sfi` | 75,984 | `1A0B515EC5DCDD60` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 932,272 | `A768EEA6B0400507` |

### 从 `MHBTW.../GAP_CERT/x64/ibtusbpts.sys` 提取

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 17 | `282F0FE4D1B59BFA` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 990,064 | `C81C309BC2814103` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 787,552 | `E815A42E338DE739` |
| `sfi_BLAZARU_A0_FMPC0_LC3.sfi` | 75,984 | `77DCB93213E66658` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 960,436 | `211A28FF8474E183` |

### 从 `SBHBTW.../GAP/x64/ibtusbpts.sys` 提取

| 文件 | 大小 | SHA256 前缀 |
|---|---:|---|
| `bseq_BLAZARU_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_FMP_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_FMP_C0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_WHP_A0.bseq` | 22 | `726B8A827EBCFDC2` |
| `bseq_BLAZARU_A0_WHP_STC.bseq` | 22 | `726B8A827EBCFDC2` |
| `sfi_BLAZARU_A0.sfi` | 905,488 | `852CC197746978F1` |
| `sfi_BLAZARU_A0_FMP_A0.sfi` | 978,608 | `F7E212C78BD96FD6` |
| `sfi_BLAZARU_A0_FMP_A0_REDUCED.sfi` | 842,512 | `81955A0EDD96DE70` |
| `sfi_BLAZARU_A0_FMP_C0.sfi` | 978,688 | `95B30088980C8497` |
| `sfi_BLAZARU_A0_FMP_C0_REDUCED.sfi` | 842,576 | `8DED88A2A4C20CB9` |
| `sfi_BLAZARU_A0_WHP_A0.sfi` | 969,792 | `62D2C260BB8FC678` |
| `sfi_BLAZARU_A0_WHP_STC.sfi` | 991,984 | `6686DCD5B890C7AB` |

## 实用建议

1. 对 `USB\VID_8087&PID_0036`，使用签名的 `SBHBTW.../GAP/x64/` PTS 包。
2. `MHBTW.../GAP_CERT/x64/` 应保留给 PID0041 / GAP certification 设备。
3. 如果需要 24.20 版本的 PID0036 PTS 驱动，应获取真正的 `MHBTW.../FRE/IntelPTS/USB/GAP/x64/` 组件，而不是改 `GAP_CERT`。
4. 不要在生产环境中修改已签名的 INF/CAT 驱动包。若要测试修改版 INF，应使用隔离的测试签名 Windows 环境。
5. 提取出的 `.sfi` / `.bseq` 应视为和驱动版本、组件、silicon stepping 绑定的固件 payload。跨 PID、跨包混用可能触发固件验证失败，甚至导致控制器需要断电重枚举或用已知可用驱动恢复。
