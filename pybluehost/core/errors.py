from __future__ import annotations


class PyBlueHostError(Exception):
    """Base exception for all PyBlueHost errors."""


class TransportError(PyBlueHostError):
    """Transport layer error (USB disconnect, serial timeout, etc.)."""


class HCIError(PyBlueHostError):
    """HCI layer error with optional status code."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class L2CAPError(PyBlueHostError):
    """L2CAP layer error."""


class GATTError(PyBlueHostError):
    """GATT layer error with optional ATT error code."""

    def __init__(self, message: str, att_error: int = 0) -> None:
        super().__init__(message)
        self.att_error = att_error


class SMPError(PyBlueHostError):
    """SMP layer error with optional reason code."""

    def __init__(self, message: str, reason: int = 0) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidTransitionError(PyBlueHostError):
    """Raised when a state machine receives an event with no defined transition."""

    def __init__(self, sm_name: str, from_state: str, event: str) -> None:
        self.sm_name = sm_name
        self.from_state = from_state
        self.event = event
        super().__init__(
            f"{sm_name}: no transition from {from_state} via {event}"
        )


class TimeoutError(PyBlueHostError):
    """Operation timed out."""

    def __init__(self, message: str, timeout: float = 0.0) -> None:
        super().__init__(message)
        self.timeout = timeout


class CommandTimeoutError(HCIError):
    """Raised when an HCI command does not receive a response within the timeout."""


class USBAccessDeniedError(TransportError):
    """USB device access denied with diagnostic report."""

    def __init__(self, report: dict) -> None:
        self.report = report
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        lines = [f"[错误] 无法访问 {self.report['device_name']}: Access denied"]
        lines.append(f"\n诊断: {self._diagnosis_line()}")
        lines.append("\n解决步骤:")
        for i, step in enumerate(self.report["steps"], 1):
            lines.append(f"  {i}. {step}")
        if self.report.get("manual_url"):
            lines.append(f"\n参考: {self.report['manual_url']}")
        return "\n".join(lines)

    def _diagnosis_line(self) -> str:
        driver = self.report.get("driver_type")
        if driver == "bthusb":
            return "设备当前由 Windows 蓝牙驱动 (bthusb.sys) 控制，WinUSB 无法获取访问权限。"
        if driver == "winusb":
            return "设备已绑定 WinUSB 驱动，但可能被其他进程占用。"
        return "USB 设备访问被拒绝，请检查驱动和权限。"


class IntelFirmwareStateError(TransportError):
    """Intel device in a state requiring full power cycle."""

    def __init__(self, device_name: str) -> None:
        super().__init__(
            f"[错误] {device_name}: 设备固件状态异常\n\n"
            "诊断: 设备已进入需要完全掉电的异常状态。\n"
            "      这是 Intel 蓝牙芯片的已知特性，简单重启无法恢复。\n\n"
            "解决步骤:\n"
            "  1. 完全关机（不是重启）\n"
            "  2. 等待 10 秒确保完全掉电\n"
            "  3. 重新开机\n"
            "  4. 重新运行程序"
        )
