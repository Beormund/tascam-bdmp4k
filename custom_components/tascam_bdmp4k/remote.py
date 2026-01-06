from typing import Any
from collections.abc import Iterable
from homeassistant.components.remote import RemoteEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN
from .tascam import TascamState

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the Tascam remote platform from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TascamRemote(coordinator, entry)])

class TascamRemote(CoordinatorEntity, RemoteEntity):
    """Remote control representation for the Tascam BD-MP4k."""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._client = coordinator.client
        self._entry = entry
        self._attr_unique_id = f"{self._client.host}_remote"
        self._attr_name = None
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._client.mac_address or self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Tascam",
            model="BD-MP4k",
        )

    @property
    def is_on(self) -> bool:
        """Remote is on unless the transport state is explicitly OFF."""
        return self._client.transport_state != TascamState.OFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wakes the unit via WOL/Power command."""
        await self._client.power_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Triggers the 'Clean Exit' shutdown logic."""
        await self._client.power_off()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Standard HA Remote API mapping all functions."""
        if not self._client:
            return
        for cmd in command:
            # --- Navigation & Menu ---
            if cmd == "up": await self._client.up()
            elif cmd == "down": await self._client.down()
            elif cmd == "left": await self._client.left()
            elif cmd == "right": await self._client.right()
            elif cmd == "enter": await self._client.enter()
            elif cmd == "back": await self._client.back()
            elif cmd == "home": await self._client.home()
            elif cmd == "setup": await self._client.setup()
            elif cmd == "top_menu": await self._client.top_menu()
            elif cmd == "popup_menu": await self._client.popup()
            elif cmd == "option": await self._client.option()
            elif cmd == "info": await self._client.info()

            # --- Transport (Mirrored for automation flexibility) ---
            elif cmd == "play": await self._client.play()
            elif cmd == "stop": await self._client.stop()
            elif cmd == "pause": await self._client.pause()
            elif cmd == "next": await self._client.next()
            elif cmd == "previous": await self._client.previous()
            elif cmd == "ff": await self._client.ff()
            elif cmd == "rw": await self._client.rr()

            # --- Audio & Utility ---
            elif cmd == "audio": await self._client.audio_dialog()
            elif cmd == "subtitle": await self._client.subtitle()
            elif cmd == "mute_on": await self._client.mute_on()
            elif cmd == "mute_off": await self._client.mute_off()
            elif cmd == "power_on": await self._client.power_on()
            elif cmd == "power_off": await self._client.power_off()
            elif cmd == "toggle_tray": await self._client.toggle_tray()
            elif cmd == "toggle_mute": await self._client.toggle_mute()

            # --- Raw Pass-through ---
            # Allows users to send raw codes directly via remote entity
            else:
                await self._client.send_command(cmd)