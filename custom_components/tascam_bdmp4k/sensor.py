from datetime import date, datetime

from decimal import Decimal
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity, StateType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from .const import DOMAIN
from . import TascamDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up Tascam sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # We pass the coordinator to each sensor
    async_add_entities([
        TascamTransportSensor(coordinator, entry),
        TascamTraySensor(coordinator, entry),
        TascamMuteSensor(coordinator, entry),
        TascamCurrentTitleSensor(coordinator, entry),
        TascamTotalTitleSensor(coordinator, entry),
        TascamCurrentChapterSensor(coordinator, entry),
        TascamTotalChapterSensor(coordinator, entry),
        TascamDiscSensor(coordinator, entry),
        TascamElapsedTimeSensor(coordinator, entry),
        TascamRemainingTimeSensor(coordinator, entry),
        TascamTotalTimeSensor(coordinator, entry)
    ])

class TascamSensorBase(CoordinatorEntity[TascamDataUpdateCoordinator], SensorEntity):
    """Base class for Tascam sensors."""

    _attr_should_poll = False

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._client = coordinator.client
        self._entry = entry
        # Unique ID Logic: Combines host/mac with a slug of the sensor name
        # This ensures 'sensor.tascam_tray_status' stays unique even with multiple units
        slug = str(self._attr_name or "sensor").lower().replace(" ", "_")
        self._attr_unique_id = f"{self._client.mac_address or self._entry.entry_id}_{slug}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._client.mac_address or entry.entry_id)},
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle pushed data from the Tascam callback."""
        # This is what makes it 'responsive' like the media_player
        self.async_write_ha_state()

    # Helper for Time Formatting
    def format_sec(self, s):
        h, rem = divmod(max(0, s), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

class TascamTransportSensor(TascamSensorBase):
    """Sensor for Play/Pause/Stop state."""
    _attr_name = "Tascam Transport State"

    @property
    def native_value(self) -> StateType:
        # Using the direct client reference as you suggested!
        return getattr(self._client.transport_state, "value", "Unknown")

class TascamTraySensor(TascamSensorBase):
    """Sensor for Disc Tray state."""
    _attr_name = "Tascam Tray Status"

    @property
    def native_value(self) -> StateType:
        return "Open" if self._client.tray_open else "Closed"

class TascamMuteSensor(TascamSensorBase):
    """Sensor for Mute state."""
    _attr_name = "Tascam Mute Status"

    @property
    def native_value(self) -> StateType:
        return "Muted" if self._client.is_muted else "Unmuted"

class TascamCurrentTitleSensor(TascamSensorBase):
    """Sensor for Current Title / Group Number."""
    _attr_name = "Tascam Current Title Status"

    @property
    def native_value(self) -> StateType:
        return self._client.current_group

class TascamTotalTitleSensor(TascamSensorBase):
    """Sensor for Total Number of Titles / Groups."""
    _attr_name = "Tascam Total Title Status"

    @property
    def native_value(self) -> StateType:
        return self._client.total_groups

class TascamCurrentChapterSensor(TascamSensorBase):
    """Sensor for Current Chapter / Track."""
    _attr_name = "Tascam Current Chapter Status"

    @property
    def native_value(self) -> StateType:
        return self._client.current_track

class TascamTotalChapterSensor(TascamSensorBase):
    """Sensor for Total Number of Chapters / Tracks."""
    _attr_name = "Tascam Total Chapter Status"

    @property
    def native_value(self) -> StateType:
        return self._client.total_tracks

class TascamDiscSensor(TascamSensorBase):
    """Sensor for Disc Status."""
    _attr_name = "Tascam Disc Status"

    @property
    def native_value(self) -> StateType:
        return getattr(self._client.disc_status, "value", "Unknown")

class TascamElapsedTimeSensor(TascamSensorBase):
    """Exposes '00:01:22' format for the dashboard."""
    _attr_icon = "mdi:clock-digital"
    _attr_name = "Tascam Elapsed Time"

    @property
    def native_value(self) -> StateType:
        return self.format_sec(self._client.elapsed_seconds)

class TascamRemainingTimeSensor(TascamSensorBase):
    """Exposes '00:01:22' format for the dashboard."""
    _attr_icon = "mdi:clock-digital"
    _attr_name = "Tascam Remaining Time"

    @property
    def native_value(self) -> StateType:
        return self.format_sec(self._client.remaining_seconds)

class TascamTotalTimeSensor(TascamSensorBase):
    """Exposes '00:01:22' format for the dashboard."""
    _attr_icon = "mdi:clock-digital"
    _attr_name = "Tascam Total Time"

    @property
    def native_value(self) -> StateType:
        return self.format_sec(self._client.total_seconds)