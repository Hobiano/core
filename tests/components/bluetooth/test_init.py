"""Tests for the Bluetooth integration."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from bleak import BleakError
from bleak.backends.scanner import AdvertisementData, BLEDevice
import pytest

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    SOURCE_LOCAL,
    UNAVAILABLE_TRACK_SECONDS,
    BluetoothChange,
    BluetoothServiceInfo,
    async_track_unavailable,
    models,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from . import _get_underlying_scanner

from tests.common import MockConfigEntry, async_fire_time_changed


async def test_setup_and_stop(hass, mock_bleak_scanner_start, enable_bluetooth):
    """Test we and setup and stop the scanner."""
    mock_bt = [
        {"domain": "switchbot", "service_uuid": "cba20d00-224d-11e6-9fb8-0002a5d5c51b"}
    ]
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ), patch.object(hass.config_entries.flow, "async_init"):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert len(mock_bleak_scanner_start.mock_calls) == 1


async def test_setup_and_stop_no_bluetooth(hass, caplog):
    """Test we fail gracefully when bluetooth is not available."""
    mock_bt = [
        {"domain": "switchbot", "service_uuid": "cba20d00-224d-11e6-9fb8-0002a5d5c51b"}
    ]
    with patch(
        "homeassistant.components.bluetooth.HaBleakScanner.async_setup",
        side_effect=BleakError,
    ) as mock_ha_bleak_scanner, patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert len(mock_ha_bleak_scanner.mock_calls) == 1
    assert "Failed to initialize Bluetooth" in caplog.text


async def test_setup_and_stop_broken_bluetooth(hass, caplog):
    """Test we fail gracefully when bluetooth/dbus is broken."""
    mock_bt = [
        {"domain": "switchbot", "service_uuid": "cba20d00-224d-11e6-9fb8-0002a5d5c51b"}
    ]

    with patch("homeassistant.components.bluetooth.HaBleakScanner.async_setup"), patch(
        "homeassistant.components.bluetooth.HaBleakScanner.start",
        side_effect=BleakError,
    ), patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert "Failed to start Bluetooth" in caplog.text
    assert len(bluetooth.async_discovered_service_info(hass)) == 0


async def test_calling_async_discovered_devices_no_bluetooth(hass, caplog):
    """Test we fail gracefully when asking for discovered devices and there is no blueooth."""
    mock_bt = []
    with patch(
        "homeassistant.components.bluetooth.HaBleakScanner.async_setup",
        side_effect=FileNotFoundError,
    ), patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert "Failed to initialize Bluetooth" in caplog.text
    assert not bluetooth.async_discovered_service_info(hass)
    assert not bluetooth.async_address_present(hass, "aa:bb:bb:dd:ee:ff")


async def test_discovery_match_by_service_uuid(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test bluetooth discovery match by service_uuid."""
    mock_bt = [
        {"domain": "switchbot", "service_uuid": "cba20d00-224d-11e6-9fb8-0002a5d5c51b"}
    ]
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ), patch.object(hass.config_entries.flow, "async_init") as mock_config_flow:
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        wrong_device = BLEDevice("44:44:33:11:23:45", "wrong_name")
        wrong_adv = AdvertisementData(local_name="wrong_name", service_uuids=[])

        _get_underlying_scanner()._callback(wrong_device, wrong_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 0

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand", service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]
        )

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 1
        assert mock_config_flow.mock_calls[0][1][0] == "switchbot"


async def test_discovery_match_by_local_name(hass, mock_bleak_scanner_start):
    """Test bluetooth discovery match by local_name."""
    mock_bt = [{"domain": "switchbot", "local_name": "wohand"}]
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init") as mock_config_flow:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        wrong_device = BLEDevice("44:44:33:11:23:45", "wrong_name")
        wrong_adv = AdvertisementData(local_name="wrong_name", service_uuids=[])

        _get_underlying_scanner()._callback(wrong_device, wrong_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 0

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(local_name="wohand", service_uuids=[])

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 1
        assert mock_config_flow.mock_calls[0][1][0] == "switchbot"


async def test_discovery_match_by_manufacturer_id_and_first_byte(
    hass, mock_bleak_scanner_start
):
    """Test bluetooth discovery match by manufacturer_id and manufacturer_data_start."""
    mock_bt = [
        {
            "domain": "homekit_controller",
            "manufacturer_id": 76,
            "manufacturer_data_start": [0x06, 0x02, 0x03],
        }
    ]
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init") as mock_config_flow:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        hkc_device = BLEDevice("44:44:33:11:23:45", "lock")
        hkc_adv = AdvertisementData(
            local_name="lock",
            service_uuids=[],
            manufacturer_data={76: b"\x06\x02\x03\x99"},
        )

        _get_underlying_scanner()._callback(hkc_device, hkc_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 1
        assert mock_config_flow.mock_calls[0][1][0] == "homekit_controller"
        mock_config_flow.reset_mock()

        # 2nd discovery should not generate another flow
        _get_underlying_scanner()._callback(hkc_device, hkc_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 0

        mock_config_flow.reset_mock()
        not_hkc_device = BLEDevice("44:44:33:11:23:21", "lock")
        not_hkc_adv = AdvertisementData(
            local_name="lock", service_uuids=[], manufacturer_data={76: b"\x02"}
        )

        _get_underlying_scanner()._callback(not_hkc_device, not_hkc_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 0
        not_apple_device = BLEDevice("44:44:33:11:23:23", "lock")
        not_apple_adv = AdvertisementData(
            local_name="lock", service_uuids=[], manufacturer_data={21: b"\x02"}
        )

        _get_underlying_scanner()._callback(not_apple_device, not_apple_adv)
        await hass.async_block_till_done()

        assert len(mock_config_flow.mock_calls) == 0


async def test_async_discovered_device_api(hass, mock_bleak_scanner_start):
    """Test the async_discovered_device API."""
    mock_bt = []
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ), patch(
        "bleak.BleakScanner.discovered_devices",  # Must patch before we setup
        [MagicMock(address="44:44:33:11:23:45")],
    ):
        assert not bluetooth.async_discovered_service_info(hass)
        assert not bluetooth.async_address_present(hass, "44:44:22:22:11:22")
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

        with patch.object(hass.config_entries.flow, "async_init"):
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
            await hass.async_block_till_done()

            assert len(mock_bleak_scanner_start.mock_calls) == 1

            assert not bluetooth.async_discovered_service_info(hass)

            wrong_device = BLEDevice("44:44:33:11:23:42", "wrong_name")
            wrong_adv = AdvertisementData(local_name="wrong_name", service_uuids=[])
            _get_underlying_scanner()._callback(wrong_device, wrong_adv)
            switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
            switchbot_adv = AdvertisementData(local_name="wohand", service_uuids=[])
            _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
            wrong_device_went_unavailable = False
            switchbot_device_went_unavailable = False

            @callback
            def _wrong_device_unavailable_callback(_address: str) -> None:
                """Wrong device unavailable callback."""
                nonlocal wrong_device_went_unavailable
                wrong_device_went_unavailable = True
                raise ValueError("blow up")

            @callback
            def _switchbot_device_unavailable_callback(_address: str) -> None:
                """Switchbot device unavailable callback."""
                nonlocal switchbot_device_went_unavailable
                switchbot_device_went_unavailable = True

            wrong_device_unavailable_cancel = async_track_unavailable(
                hass, _wrong_device_unavailable_callback, wrong_device.address
            )
            switchbot_device_unavailable_cancel = async_track_unavailable(
                hass, _switchbot_device_unavailable_callback, switchbot_device.address
            )

            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=UNAVAILABLE_TRACK_SECONDS)
            )
            await hass.async_block_till_done()

            service_infos = bluetooth.async_discovered_service_info(hass)
            assert switchbot_device_went_unavailable is False
            assert wrong_device_went_unavailable is True

            # See the devices again
            _get_underlying_scanner()._callback(wrong_device, wrong_adv)
            _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
            # Cancel the callbacks
            wrong_device_unavailable_cancel()
            switchbot_device_unavailable_cancel()
            wrong_device_went_unavailable = False
            switchbot_device_went_unavailable = False

            # Verify the cancel is effective
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=UNAVAILABLE_TRACK_SECONDS)
            )
            await hass.async_block_till_done()
            assert switchbot_device_went_unavailable is False
            assert wrong_device_went_unavailable is False

            assert len(service_infos) == 1
            # wrong_name should not appear because bleak no longer sees it
            assert service_infos[0].name == "wohand"
            assert service_infos[0].source == SOURCE_LOCAL
            assert isinstance(service_infos[0].device, BLEDevice)
            assert isinstance(service_infos[0].advertisement, AdvertisementData)

            assert bluetooth.async_address_present(hass, "44:44:33:11:23:42") is False
            assert bluetooth.async_address_present(hass, "44:44:33:11:23:45") is True


async def test_register_callbacks(hass, mock_bleak_scanner_start, enable_bluetooth):
    """Test registering a callback."""
    mock_bt = []
    callbacks = []

    def _fake_subscriber(
        service_info: BluetoothServiceInfo,
        change: BluetoothChange,
    ) -> None:
        """Fake subscriber for the BleakScanner."""
        callbacks.append((service_info, change))
        if len(callbacks) >= 3:
            raise ValueError

    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ), patch.object(hass.config_entries.flow, "async_init"):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        cancel = bluetooth.async_register_callback(
            hass,
            _fake_subscriber,
            {"service_uuids": {"cba20d00-224d-11e6-9fb8-0002a5d5c51b"}},
        )

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)

        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        # 3rd callback raises ValueError but is still tracked
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

        cancel()

        # 4th callback should not be tracked since we canceled
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

    assert len(callbacks) == 3

    service_info: BluetoothServiceInfo = callbacks[0][0]
    assert service_info.name == "wohand"
    assert service_info.source == SOURCE_LOCAL
    assert service_info.manufacturer == "Nordic Semiconductor ASA"
    assert service_info.manufacturer_id == 89

    service_info: BluetoothServiceInfo = callbacks[1][0]
    assert service_info.name == "empty"
    assert service_info.source == SOURCE_LOCAL
    assert service_info.manufacturer is None
    assert service_info.manufacturer_id is None

    service_info: BluetoothServiceInfo = callbacks[2][0]
    assert service_info.name == "empty"
    assert service_info.source == SOURCE_LOCAL
    assert service_info.manufacturer is None
    assert service_info.manufacturer_id is None


async def test_register_callback_by_address(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test registering a callback by address."""
    mock_bt = []
    callbacks = []

    def _fake_subscriber(
        service_info: BluetoothServiceInfo, change: BluetoothChange
    ) -> None:
        """Fake subscriber for the BleakScanner."""
        callbacks.append((service_info, change))
        if len(callbacks) >= 3:
            raise ValueError

    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        cancel = bluetooth.async_register_callback(
            hass,
            _fake_subscriber,
            {"address": "44:44:33:11:23:45"},
        )

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)

        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        # 3rd callback raises ValueError but is still tracked
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

        cancel()

        # 4th callback should not be tracked since we canceled
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        await hass.async_block_till_done()

        # Now register again with a callback that fails to
        # make sure we do not perm fail
        cancel = bluetooth.async_register_callback(
            hass,
            _fake_subscriber,
            {"address": "44:44:33:11:23:45"},
        )
        cancel()

        # Now register again, since the 3rd callback
        # should fail but we should still record it
        cancel = bluetooth.async_register_callback(
            hass,
            _fake_subscriber,
            {"address": "44:44:33:11:23:45"},
        )
        cancel()

    assert len(callbacks) == 3

    for idx in range(3):
        service_info: BluetoothServiceInfo = callbacks[idx][0]
        assert service_info.name == "wohand"
        assert service_info.manufacturer == "Nordic Semiconductor ASA"
        assert service_info.manufacturer_id == 89


async def test_wrapped_instance_with_filter(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test consumers can use the wrapped instance with a filter as if it was normal BleakScanner."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        detected = []

        def _device_detected(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            """Handle a detected device."""
            detected.append((device, advertisement_data))

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )
        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper(
            filters={"UUIDs": ["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]}
        )
        scanner.register_detection_callback(_device_detected)

        mock_discovered = [MagicMock()]
        type(_get_underlying_scanner()).discovered_devices = mock_discovered
        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()

        discovered = await scanner.discover(timeout=0)
        assert len(discovered) == 1
        assert discovered == mock_discovered
        assert len(detected) == 1

        scanner.register_detection_callback(_device_detected)
        # We should get a reply from the history when we register again
        assert len(detected) == 2
        scanner.register_detection_callback(_device_detected)
        # We should get a reply from the history when we register again
        assert len(detected) == 3

        type(_get_underlying_scanner()).discovered_devices = []
        discovered = await scanner.discover(timeout=0)
        assert len(discovered) == 0
        assert discovered == []

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        assert len(detected) == 4

        # The filter we created in the wrapped scanner with should be respected
        # and we should not get another callback
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        assert len(detected) == 4


async def test_wrapped_instance_with_service_uuids(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test consumers can use the wrapped instance with a service_uuids list as if it was normal BleakScanner."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        detected = []

        def _device_detected(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            """Handle a detected device."""
            detected.append((device, advertisement_data))

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )
        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper(
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]
        )
        scanner.register_detection_callback(_device_detected)

        type(_get_underlying_scanner()).discovered_devices = [MagicMock()]
        for _ in range(2):
            _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
            await hass.async_block_till_done()

        assert len(detected) == 2

        # The UUIDs list we created in the wrapped scanner with should be respected
        # and we should not get another callback
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        assert len(detected) == 2


async def test_wrapped_instance_with_broken_callbacks(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test broken callbacks do not cause the scanner to fail."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ), patch.object(hass.config_entries.flow, "async_init"):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        detected = []

        def _device_detected(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            """Handle a detected device."""
            if detected:
                raise ValueError
            detected.append((device, advertisement_data))

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )

        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper(
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]
        )
        scanner.register_detection_callback(_device_detected)

        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()
        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()
        assert len(detected) == 1


async def test_wrapped_instance_changes_uuids(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test consumers can use the wrapped instance can change the uuids later."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        detected = []

        def _device_detected(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            """Handle a detected device."""
            detected.append((device, advertisement_data))

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )
        empty_device = BLEDevice("11:22:33:44:55:66", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper()
        scanner.set_scanning_filter(
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]
        )
        scanner.register_detection_callback(_device_detected)

        type(_get_underlying_scanner()).discovered_devices = [MagicMock()]
        for _ in range(2):
            _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
            await hass.async_block_till_done()

        assert len(detected) == 2

        # The UUIDs list we created in the wrapped scanner with should be respected
        # and we should not get another callback
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        assert len(detected) == 2


async def test_wrapped_instance_changes_filters(
    hass, mock_bleak_scanner_start, enable_bluetooth
):
    """Test consumers can use the wrapped instance can change the filter later."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        detected = []

        def _device_detected(
            device: BLEDevice, advertisement_data: AdvertisementData
        ) -> None:
            """Handle a detected device."""
            detected.append((device, advertisement_data))

        switchbot_device = BLEDevice("44:44:33:11:23:42", "wohand")
        switchbot_adv = AdvertisementData(
            local_name="wohand",
            service_uuids=["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
            manufacturer_data={89: b"\xd8.\xad\xcd\r\x85"},
            service_data={"00000d00-0000-1000-8000-00805f9b34fb": b"H\x10c"},
        )
        empty_device = BLEDevice("11:22:33:44:55:62", "empty")
        empty_adv = AdvertisementData(local_name="empty")

        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper()
        scanner.set_scanning_filter(
            filters={"UUIDs": ["cba20d00-224d-11e6-9fb8-0002a5d5c51b"]}
        )
        scanner.register_detection_callback(_device_detected)

        type(_get_underlying_scanner()).discovered_devices = [MagicMock()]
        for _ in range(2):
            _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
            await hass.async_block_till_done()

        assert len(detected) == 2

        # The UUIDs list we created in the wrapped scanner with should be respected
        # and we should not get another callback
        _get_underlying_scanner()._callback(empty_device, empty_adv)
        assert len(detected) == 2


async def test_wrapped_instance_unsupported_filter(
    hass, mock_bleak_scanner_start, caplog, enable_bluetooth
):
    """Test we want when their filter is ineffective."""
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=[]
    ):
        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        await hass.async_block_till_done()

    with patch.object(hass.config_entries.flow, "async_init"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        assert _get_underlying_scanner() is not None
        scanner = models.HaBleakScannerWrapper()
        scanner.set_scanning_filter(
            filters={
                "unsupported": ["cba20d00-224d-11e6-9fb8-0002a5d5c51b"],
                "DuplicateData": True,
            }
        )
        assert "Only UUIDs filters are supported" in caplog.text


async def test_async_ble_device_from_address(hass, mock_bleak_scanner_start):
    """Test the async_ble_device_from_address api."""
    mock_bt = []
    with patch(
        "homeassistant.components.bluetooth.async_get_bluetooth", return_value=mock_bt
    ), patch(
        "bleak.BleakScanner.discovered_devices",  # Must patch before we setup
        [MagicMock(address="44:44:33:11:23:45")],
    ):
        assert not bluetooth.async_discovered_service_info(hass)
        assert not bluetooth.async_address_present(hass, "44:44:22:22:11:22")
        assert (
            bluetooth.async_ble_device_from_address(hass, "44:44:33:11:23:45") is None
        )

        assert await async_setup_component(
            hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}}
        )
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert len(mock_bleak_scanner_start.mock_calls) == 1

        assert not bluetooth.async_discovered_service_info(hass)

        switchbot_device = BLEDevice("44:44:33:11:23:45", "wohand")
        switchbot_adv = AdvertisementData(local_name="wohand", service_uuids=[])
        _get_underlying_scanner()._callback(switchbot_device, switchbot_adv)
        await hass.async_block_till_done()

        assert (
            bluetooth.async_ble_device_from_address(hass, "44:44:33:11:23:45")
            is switchbot_device
        )

        assert (
            bluetooth.async_ble_device_from_address(hass, "00:66:33:22:11:22") is None
        )


async def test_setup_without_bluetooth_in_configuration_yaml(hass, mock_bluetooth):
    """Test setting up without bluetooth in configuration.yaml does not create the config entry."""
    assert await async_setup_component(hass, bluetooth.DOMAIN, {})
    await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(bluetooth.DOMAIN)


async def test_setup_with_bluetooth_in_configuration_yaml(hass, mock_bluetooth):
    """Test setting up with bluetooth in configuration.yaml creates the config entry."""
    assert await async_setup_component(hass, bluetooth.DOMAIN, {bluetooth.DOMAIN: {}})
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(bluetooth.DOMAIN)


async def test_can_unsetup_bluetooth(hass, mock_bleak_scanner_start, enable_bluetooth):
    """Test we can setup and unsetup bluetooth."""
    entry = MockConfigEntry(domain=bluetooth.DOMAIN, data={})
    entry.add_to_hass(hass)
    for _ in range(2):

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_auto_detect_bluetooth_adapters_linux(hass):
    """Test we auto detect bluetooth adapters on linux."""
    with patch(
        "bluetooth_adapters.get_bluetooth_adapters", return_value={"hci0"}
    ), patch(
        "homeassistant.components.bluetooth.platform.system", return_value="Linux"
    ):
        assert await async_setup_component(hass, bluetooth.DOMAIN, {})
        await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(bluetooth.DOMAIN)
    assert len(hass.config_entries.flow.async_progress(bluetooth.DOMAIN)) == 1


async def test_auto_detect_bluetooth_adapters_linux_none_found(hass):
    """Test we auto detect bluetooth adapters on linux with no adapters found."""
    with patch("bluetooth_adapters.get_bluetooth_adapters", return_value=set()), patch(
        "homeassistant.components.bluetooth.platform.system", return_value="Linux"
    ):
        assert await async_setup_component(hass, bluetooth.DOMAIN, {})
        await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(bluetooth.DOMAIN)
    assert len(hass.config_entries.flow.async_progress(bluetooth.DOMAIN)) == 0


async def test_auto_detect_bluetooth_adapters_macos(hass):
    """Test we auto detect bluetooth adapters on macos."""
    with patch(
        "homeassistant.components.bluetooth.platform.system", return_value="Darwin"
    ):
        assert await async_setup_component(hass, bluetooth.DOMAIN, {})
        await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(bluetooth.DOMAIN)
    assert len(hass.config_entries.flow.async_progress(bluetooth.DOMAIN)) == 1


async def test_no_auto_detect_bluetooth_adapters_windows(hass):
    """Test we auto detect bluetooth adapters on windows."""
    with patch(
        "homeassistant.components.bluetooth.platform.system", return_value="Windows"
    ):
        assert await async_setup_component(hass, bluetooth.DOMAIN, {})
        await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(bluetooth.DOMAIN)
    assert len(hass.config_entries.flow.async_progress(bluetooth.DOMAIN)) == 0


async def test_raising_runtime_error_when_no_bluetooth(hass):
    """Test we raise an exception if we try to get the scanner when its not there."""
    with pytest.raises(RuntimeError):
        bluetooth.async_get_scanner(hass)


async def test_getting_the_scanner_returns_the_wrapped_instance(hass, enable_bluetooth):
    """Test getting the scanner returns the wrapped instance."""
    scanner = bluetooth.async_get_scanner(hass)
    assert isinstance(scanner, models.HaBleakScannerWrapper)
