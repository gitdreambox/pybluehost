"""PTS IUT mode configuration — opt-in flags adjusting stack behavior for PTS testing."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PTSModeConfig:
    """Opt-in PTS-mode tweaks. Attach via ``StackConfig.pts``; ``None`` (default)
    means zero behavior change vs v1.0/v1.1.

    See design spec §3. Each flag's hook is wired in a separate Plan task:
      - secure_pair_only       → Task 2 (SecurityConfig.sc_only_mode build-time wire)
      - smp_options            → Task 3 (SMP pairing request/response byte override)
      - smp_failure_at         → Task 4 (inject SMPPairingFailed at named stage)
      - disable_sdp_on_le_pair → Task 5 (skip auto SDP/CTKD-classic after LE pair)
      - disable_conn_updates   → defensive guard only — no auto LE conn-param-update
                                 sender exists in the stack today; ANY future sender
                                 MUST consult this flag.
    """

    disable_conn_updates: bool = False
    secure_pair_only: bool = False
    disable_sdp_on_le_pair: bool = False
    smp_options: bytes | None = None
    smp_failure_at: str | None = None
