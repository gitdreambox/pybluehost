"""Unified GAP entry point — combines BLE and Classic GAP subsystems."""
from __future__ import annotations

from pybluehost.ble.gap import (
    BLEAdvertiser,
    BLEConnectionManager,
    BLEScanner,
    ExtendedAdvertiser,
    PrivacyManager,
    WhiteList,
)
from pybluehost.classic.gap import (
    ClassicConnectionManager,
    ClassicDiscoverability,
    ClassicDiscovery,
    SSPManager,
)


class GAP:
    """Unified GAP — single entry point for BLE + Classic GAP operations.

    Holds references to all GAP subsystem controllers and provides
    ``set_pairing_delegate()`` to wire a common pairing delegate into
    both BLE SMP and Classic SSP.
    """

    def __init__(
        self,
        ble_advertiser: BLEAdvertiser | None = None,
        ble_scanner: BLEScanner | None = None,
        ble_connections: BLEConnectionManager | None = None,
        ble_privacy: PrivacyManager | None = None,
        classic_discovery: ClassicDiscovery | None = None,
        classic_discoverability: ClassicDiscoverability | None = None,
        classic_connections: ClassicConnectionManager | None = None,
        classic_ssp: SSPManager | None = None,
        whitelist: WhiteList | None = None,
        ble_extended_advertiser: ExtendedAdvertiser | None = None,
    ) -> None:
        self._ble_advertiser = ble_advertiser
        self._ble_scanner = ble_scanner
        self._ble_connections = ble_connections
        self._ble_privacy = ble_privacy
        self._classic_discovery = classic_discovery
        self._classic_discoverability = classic_discoverability
        self._classic_connections = classic_connections
        self._classic_ssp = classic_ssp
        self._whitelist = whitelist
        self._ble_extended_advertiser = ble_extended_advertiser
        self._pairing_delegate: object | None = None

    # -- BLE properties ------------------------------------------------------

    @property
    def ble_advertiser(self) -> BLEAdvertiser | None:
        return self._ble_advertiser

    @property
    def ble_scanner(self) -> BLEScanner | None:
        return self._ble_scanner

    @property
    def ble_connections(self) -> BLEConnectionManager | None:
        return self._ble_connections

    @property
    def ble_privacy(self) -> PrivacyManager | None:
        return self._ble_privacy

    @property
    def whitelist(self) -> WhiteList | None:
        return self._whitelist

    @property
    def ble_extended_advertiser(self) -> ExtendedAdvertiser | None:
        return self._ble_extended_advertiser

    # -- Classic properties --------------------------------------------------

    @property
    def classic_discovery(self) -> ClassicDiscovery | None:
        return self._classic_discovery

    @property
    def classic_discoverability(self) -> ClassicDiscoverability | None:
        return self._classic_discoverability

    @property
    def classic_connections(self) -> ClassicConnectionManager | None:
        return self._classic_connections

    @property
    def classic_ssp(self) -> SSPManager | None:
        return self._classic_ssp

    # -- Pairing delegate ----------------------------------------------------

    def set_pairing_delegate(self, delegate: object) -> None:
        """Set a common pairing delegate for both BLE SMP and Classic SSP.

        The delegate object can implement methods expected by SMPManager
        (PairingDelegate protocol) and/or SSPManager confirmation handlers.
        """
        self._pairing_delegate = delegate

    @property
    def pairing_delegate(self) -> object | None:
        return self._pairing_delegate
