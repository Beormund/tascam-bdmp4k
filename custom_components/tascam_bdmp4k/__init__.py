"""Tascam BD-MP4k integration."""
from datetime import timedelta
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import (
    DOMAIN, 
    EVENT_RAW_MESSAGE, 
    EVENT_GLOBAL_MESSAGE
)
from .tascam import TascamController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE, Platform.SENSOR]

class TascamDataUpdateCoordinator(DataUpdateCoordinator[TascamController]):
    """Class to manage pushing Tascam data to Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        client: TascamController,
        name: str,
    ) -> None:
        """Initialize."""
        self.client = client
        super().__init__(
            hass,
            logger,
            name=name,
            update_method=None, # Push-only: no polling method
            update_interval=None, # Push-only: no timer
        )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration and store the client."""
    host = entry.data[CONF_HOST]
    mac = entry.data[CONF_MAC]

    # 1. Initialize the controller client
    client = await TascamController.create(host, mac)

    # 2. Setup the Push-Only Coordinator
    coordinator = TascamDataUpdateCoordinator(
        hass,
        _LOGGER,
        client=client,
        name=f"Tascam {entry.title}",
    )

    # Pre-seed the coordinator data with the client reference
    coordinator.data = client

    # 3. Link the controller's callback to the coordinator
    @callback
    def handle_tascam_push():
        """Triggered when the Tascam Slicer receives new TCP data."""
        coordinator.async_set_updated_data(client)

    client.on_data_received_callback = handle_tascam_push    

    # 4. Setup Permanent Global Bridge
    # This fires a global event for any message type whose state has changed
    def fire_global_event(clean_msg: str):
        """Permanent listener to bridge hardware messages to the HA Event Bus."""
        hass.bus.async_fire(EVENT_GLOBAL_MESSAGE, {
            "device_id": entry.entry_id,
            "message": clean_msg
        })

    # Register the permanent global listener and ensure it unloads with the entry
    entry.async_on_unload(client.register_subscriber(fire_global_event))

    # 5. Setup Temporary Subscription Service
    async def handle_subscribe_service(call: ServiceCall):
        """Service to listen for a specific Tascam response for a set duration."""
        match = call.data.get("match")
        duration = call.data.get("duration", 10)  # Default to 10 seconds

        def fire_temp_event(raw_data: str):
            hass.bus.async_fire(EVENT_RAW_MESSAGE, {
                "device_id": entry.entry_id,
                "message": raw_data,
                "match": match
            })

        # Register the temporary listener
        unregister_fn = client.register_subscriber(fire_temp_event, match=match)
        
        # Schedule the automatic unregistration (cleanup)
        async def delayed_cleanup():
            await asyncio.sleep(duration)
            unregister_fn()

        hass.async_create_task(delayed_cleanup())

    # Register the new subscription service
    hass.services.async_register(DOMAIN, "subscribe_to_message", handle_subscribe_service)

    # --- END EVENT PLUMBING ---    

    # Store coordinator for platforms to access
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 6. Service registration
    async def handle_send_command(call: ServiceCall):
        """Service to send any !7 command string."""
        command = call.data.get("command")
        if command:
            _LOGGER.debug("Tascam sending raw command: %s", command)
            await client.send_command(command)

    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command
    )

    # 7. Forward to all platforms (Media Player, Sensor, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration and disconnect the client."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Clean shutdown of the TCP socket
        await coordinator.client.disconnect()

        # Only remove the service if this was the last Tascam unit in the house
        if not hass.data[DOMAIN]:
            for service in ["send_command", "subscribe_to_message"]:
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)

    return unload_ok