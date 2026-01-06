from collections.abc import Mapping
from datetime import datetime
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import Any, CoordinatorEntity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from .const import DOMAIN, SUPPORT_TASCAM
from .tascam import TascamState

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Set up the Tascam Media Player from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TascamMediaPlayer(coordinator, entry)])

class TascamMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Media player representation of the Tascam BD-MP4k."""

    def __init__(self, coordinator, entry) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._client = coordinator.client
        self._entry = entry
        self._attr_unique_id = f"{self._client.host}_media_player"
        self._attr_name = None
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._client.mac_address or self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Tascam",
            model="BD-MP4k",
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if not self._client:
            return None

        return {
            "native_transport_state": self._client.transport_state.value,
            "disc_status": self._client.disc_status.value,
            "tray_open": self._client.tray_open,
            "device_ip": self._client.host,
            "device_mac": self._client.mac_address,
            "last_update_successful": self.coordinator.last_update_success,
            "current_title_index": self._client.current_group,   # GNMX
            "total_titles": self._client.total_groups,         # TGNX
            "current_chapter": self._client.current_track,      # TN
            "total_chapters": self._client.total_tracks        # TT
        }

    @property
    def state(self) -> MediaPlayerState:
        """Return the current state of the player."""

        if self._client.transport_state == TascamState.OFF:
            return MediaPlayerState.OFF

        if self._client.is_media_active:
            if self._client.transport_state == TascamState.PAUSE:
                return MediaPlayerState.PAUSED
            return MediaPlayerState.PLAYING

        # 4. Standby / Stop Check
        return MediaPlayerState.IDLE

    @property
    def is_volume_muted(self) -> bool:
        """Return true if volume is muted."""
        return self._client.is_muted if self._client else False

    @property
    def media_duration(self) -> int | None:
        """Duration in seconds."""
        return self._client.total_seconds if self._client.total_seconds > 0 else None

    @property
    def media_position(self) -> int | None:
        """Position in seconds."""
        return self._client.elapsed_seconds if self._client else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was last updated."""
        if self.state == MediaPlayerState.PLAYING:
            return dt_util.utcnow()
        return None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag supported features."""
        return SUPPORT_TASCAM

    @property
    def media_track(self) -> int | None:
        """Track number of current playing media."""
        # Maps TN to the standard track field
        track = self._client.current_track
        return int(track) if track.isdigit() else None

    @property
    def media_series_title(self) -> str | None:
        """Title of the series (Disc Title/Group)."""
        # Maps GNMX to the series field
        return f"Title {self._client.current_group}"

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        # Provides a clean "Chapter X" label
        if self._client.current_track.isdigit():
            return f"Chapter {self._client.current_track}"
        return "Loading..."

    # --- Actions (No refresh needed due to Callback) ---
    async def async_turn_on(self) -> None: await self._client.power_on()
    async def async_turn_off(self) -> None: await self._client.power_off()
    async def async_media_play(self) -> None: await self._client.play()
    async def async_media_pause(self) -> None: await self._client.pause()
    async def async_media_stop(self) -> None: await self._client.stop()
    async def async_media_next_track(self) -> None: await self._client.next()
    async def async_media_previous_track(self) -> None: await self._client.previous()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute using the verified logic (00=Mute ON)."""
        cmd = "MUT00" if mute else "MUT01"
        await self._client.send_command(cmd)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle pushed data from the Tascam callback."""
        # This triggers a UI refresh whenever the client pushes new data
        self.async_write_ha_state()
