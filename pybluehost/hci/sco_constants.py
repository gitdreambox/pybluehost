"""HCI SCO transport constants — Bluetooth Core §5.4.3 / §7.1.41."""
from __future__ import annotations

# HCI packet type indicator for SCO (UART/USB only).
SCO_TRANSPORT_HCI = 0x03

# Packet Status Flag values — Bluetooth Core §5.4.3 Table 5.1.
SCO_PACKET_STATUS_OK = 0
SCO_PACKET_STATUS_INVALID = 1
SCO_PACKET_STATUS_NO_DATA = 2
SCO_PACKET_STATUS_PARTIAL = 3

# Codec IDs for HCI Setup_Synchronous_Connection (Volume 4, Part E, §7.1.41 +
# eSCO param table).
SCO_CODEC_ID_CVSD = 2     # value used in HCI's "coding_format" field
SCO_CODEC_ID_MSBC = 5     # vendor-specific in pre-5.0; standard in BT 5.0+

# Common HCI Setup_Synchronous_Connection parameter presets — HFP v1.8 §5.7.
# (Tx/Rx bandwidth, max_latency, voice setting, retransmission_effort, packet_type)
PRESET_CVSD_S1 = {
    "tx_bw": 8000, "rx_bw": 8000,
    "max_latency": 0x000A,
    "voice_setting": 0x0060,    # input coding: linear, format: 16-bit, sample rate: 8 kHz
    "retransmission_effort": 0x01,
    "packet_type": 0x0380,
}
PRESET_MSBC_T2 = {
    "tx_bw": 8000, "rx_bw": 8000,
    "max_latency": 0x000D,
    "voice_setting": 0x0063,
    "retransmission_effort": 0x02,
    "packet_type": 0x0380,
}
