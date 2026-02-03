import asyncio
import ipaddress
import logging
import socket
import re
from enum import Enum, IntFlag, auto
from typing import Optional, Callable
from asyncio import Future, StreamReader, StreamWriter

_LOGGER = logging.getLogger(__name__)

class ControllerStatus(IntFlag):
    """Bitmask representing the precise internal state of the driver."""
    NONE            = 0
    SOCKET_OPEN     = auto()  # Bit 0 (1): TCP Connection established
    HEARTBEAT_RUN   = auto()  # Bit 1 (2): Background loop is active
    SHUTTING_DOWN   = auto()  # Bit 2 (4): 15s Power-off guard is active
    WAKING_UP       = auto()  # Bit 3 (8): Power-on guard is active

    # Composite States
    READY           = SOCKET_OPEN | HEARTBEAT_RUN

class TascamState(Enum):
    PLAY = "Playing"
    PAUSE = "Paused"
    STOP = "Stopped"
    FF = "Fast Forward"
    FR = "Fast Reverse"
    SLOW_F = "Slow Forward"
    SLOW_R = "Slow Reverse"
    SETUP = "Setup Mode"
    HOME = "Home Menu"
    MEDIA_CENTER = "Media Centre"
    ROOT_MENU = "Root Menu"
    SPLASH = "Powering On"
    OFF = "Off"
    UNKNOWN = "Unknown"

class TascamDiscState(Enum):
    # Media Sources (MST codes)
    NC = "No Media"      # No disc, USB, or SD detected
    CI = "Disc"          # Optical Disc (CD/DVD/BD)
    # Tray/Error Status
    TO = "Tray Open"     # Physical tray is ejected
    TC = "Tray Closed"   # Physical tray is in (but might be empty)
    TE = "Tray Error"    # Mechanical failure
    UF = "Unknown"       # Unit is busy or state is undefinedError"

class TascamController:
    # Official Protocol Map: Codes to Enum (BD-MP4K Section 5.3)
    PROTOCOL_MAP = {
        "DVFF": TascamState.FF, "DVFR": TascamState.FR,
        "DVSF": TascamState.SLOW_F, "DVSR": TascamState.SLOW_R,
        "DVSU": TascamState.SETUP, "DVHM": TascamState.HOME,
        "DVMC": TascamState.MEDIA_CENTER, "DVTR": TascamState.ROOT_MENU,
        "DVPL": TascamState.SPLASH, "PL": TascamState.PLAY,
        "PP": TascamState.PAUSE, "ST": TascamState.STOP
    }

    MEDIA_ACTIVE_STATES = [
        TascamState.PLAY, TascamState.PAUSE, TascamState.FF,
        TascamState.FR, TascamState.SLOW_F, TascamState.SLOW_R
    ]

    def __init__(self, host: str, mac_address: Optional[str] = None, port: int = 9030) -> None:
        """Initialise the unit and start background heartbeat"""
        self.host = host
        self.mac_address = mac_address
        self.port = port
        self.reader: Optional[StreamReader] = None
        self.writer: Optional[StreamWriter] = None
        self.on_data_received_callback: Optional[Callable[[], None]] = None

        # State Management
        self._status = ControllerStatus.NONE
        self._connect_lock = asyncio.Lock()
        self._cleanup_lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._subscribers: dict[Callable[[str], None], Optional[str]] = {}

        # Media Data
        self.transport_state = TascamState.OFF
        self.tray_open = False
        self.is_muted = False
        self.disc_status = TascamDiscState.NC
        self.current_group = self.total_groups = "0"
        self.current_track = self.total_tracks = "0"
        self.elapsed_seconds = self.remaining_seconds = self.total_seconds = 0
        self.cmd_result: Optional[Future[bool]] = None
        self._background_tasks = set()
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._heartbeat())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            self._heartbeat_task = task
        except RuntimeError: pass
        
    def register_subscriber(self, callback: Callable[[str], None], match: Optional[str] = None):
        """Add a subscriber and return a function to unregister it."""
        self._subscribers[callback] = match
        self._log(f"REGISTERED SUBSCRIBER WITH MATCH {match}")
        return lambda: self.remove_subscriber(callback)

    def remove_subscriber(self, callback: Callable[[str], None]):
        """Remove a subscriber."""
        if callback in self._subscribers:
            match = self._subscribers.pop(callback)
            self._log(f"UNREGISTER SUBSCRIBER WITH MATCH {match}")

    def __repr__(self) -> str:
        """Outputs a useful string representation of the state of the controller"""
        active_flags: list[str] = [
            str(f.name) for f in ControllerStatus
            if (f in self.status and f != ControllerStatus.NONE)
        ]

        flags_str = "|".join(active_flags) if active_flags else "NONE"
        return f"<TascamController({self.host}) [{flags_str}]>"

    @classmethod
    async def create(cls, host: str, mac_address: Optional[str] = None, port: int = 9030):
        """Async factory to ensure connection is established before returning."""
        instance = cls(host, mac_address, port)
        await instance.connect()
        return instance

    @property
    def status(self) -> ControllerStatus:
        """Dynamic bitmask combining manual flags and physical connection state."""
        s = self._status
        if self.writer is not None:
            s |= ControllerStatus.SOCKET_OPEN
        else:
            s &= ~ControllerStatus.SOCKET_OPEN
        return s

    @property
    def is_connected(self) -> bool:
        """Uses internal flags to determine if the unit is connected (powered on)"""
        curr = self.status
        return (ControllerStatus.SOCKET_OPEN in curr) and \
               (ControllerStatus.SHUTTING_DOWN not in curr)

    @property
    def is_media_active(self) -> bool:
        """If unit is in one of the active media states e.g., pause, play, ff, rr"""
        return self.transport_state in self.MEDIA_ACTIVE_STATES

    # --- 1. TRANSPORT API ---
    async def play(self):
        """Commence media playback or resume from pause."""
        return await self.send_command("PLY")

    async def stop(self):
        """Halt playback and reset transport position."""
        return await self.send_command("STP")

    async def pause(self):
        """Freeze playback at the current timestamp."""
        return await self.send_command("PAS")

    async def next(self):
        """Skip to the next track or chapter index."""
        return await self.send_command("SKPNX")

    async def previous(self):
        """Return to the start of the current track or previous chapter."""
        return await self.send_command("SKPPV")

    async def ff(self):
        """Initiate high-speed forward scanning (Fast Forward)."""
        return await self.send_command("SCNFf")

    async def rr(self):
        """Initiate high-speed reverse scanning (Rewind)."""
        return await self.send_command("SCNRf")

    # --- 2. NAVIGATION API ---
    async def enter(self):
        """Confirm the current selection in the On-Screen Display."""
        return await self.send_command("ENT")

    async def back(self):
        """Return to the previous menu level or exit current view."""
        return await self.send_command("RET")

    async def up(self):
        """Move cursor up in the On-Screen Display."""
        return await self.send_command("OSD3")

    async def down(self):
        """Move cursor down in the On-Screen Display."""
        return await self.send_command("OSD4")

    async def left(self):
        """Move cursor left in the On-Screen Display."""
        return await self.send_command("OSD1")

    async def right(self):
        """Move cursor right in the On-Screen Display."""
        return await self.send_command("OSD2")

    # --- 3. MENU API ---
    async def home(self):
        """Return to the main Tascam system home screen."""
        return await self.send_command("HOM")

    async def setup(self):
        """Open the system configuration and settings menu."""
        return await self.send_command("SMN")

    async def top_menu(self):
        """Access the disc-specific root menu (DVD/Blu-ray)."""
        return await self.send_command("TMN")

    async def popup(self):
        """Invoke the disc's pop-up menu during playback."""
        return await self.send_command("PMN")

    async def option(self):
        """Display context-sensitive playback options."""
        return await self.send_command("OMN")

    async def info(self):
        """Toggle the On-Screen Display metadata and status info."""
        return await self.send_command("DSP")

    # --- 4. UTILITY & AUDIO API ---
    async def audio_dialog(self):
        """Cycle through available audio tracks/languages."""
        return await self.send_command("ADG+")

    async def subtitle(self):
        """Cycle through available subtitle tracks/closed captioning."""
        return await self.send_command("SBT1")

    async def mute_on(self):
        """Engage hardware-level audio muting (00)."""
        return await self.send_command("MUT00")

    async def mute_off(self):
        """Disengage hardware-level audio muting (01)."""
        return await self.send_command("MUT01")

    async def toggle_tray(self) -> bool:
        """Query the unit for tray status and send inverted command"""
        if not self.is_connected: return False
        await self.send_command("?MST")
        await asyncio.sleep(0.1)
        return await self.send_command("OPCCL" if self.tray_open else "OPCOP")

    async def toggle_mute(self) -> bool:
        """Query the unit for mute status and send inverted command"""
        if not self.is_connected: return False
        await self.send_command("?MUT")
        await asyncio.sleep(0.1)
        return await self.send_command("MUT01" if self.is_muted else "MUT00")

    # --- 5. POWER & CONNECTION API ---

    def get_backup_wol(self) -> str:
        """Calculate the directed subnet broadcast address based on the host IP."""
        try:
            # Assumes a standard /24 (255.255.255.0) which is 99% of home cinemas.
            # If you use a custom subnet, you can change '24' to your CIDR.
            interface = ipaddress.IPv4Interface(f"{self.host}/24")
            broadcast = str(interface.network.broadcast_address)
            return broadcast
        except Exception as e:
            self._log(f"WOL Calculation failed: {e}. Falling back to universal.")
            return "255.255.255.255"

    async def power_on(self) -> bool:
        """Try power the unit on via WOL, then fallback to PWR01 command"""
        if self.is_connected:
            return await self.send_command("PWR01")

        # 1. SET THE LOCK AND STATE IMMEDIATELY
        self._status |= ControllerStatus.WAKING_UP
        self._status &= ~ControllerStatus.SHUTTING_DOWN
        self.transport_state = TascamState.SPLASH

        # 2. TRIGGER UI IMMEDIATELY
        if self.on_data_received_callback:
            self.on_data_received_callback()

        if not self.mac_address:
            self._status &= ~ControllerStatus.WAKING_UP
            self.transport_state = TascamState.OFF # Revert if we can't wake it
            return False

        mac_clean = self.mac_address.replace(":", "").replace("-", "")
        magic_packet = b'\xff' * 6 + bytes.fromhex(mac_clean) * 16

        try:
            # 3. BROADCAST
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(magic_packet, ("255.255.255.255", 9))
                # Also try a directed subnet broadcast
                s.sendto(magic_packet, (self.get_backup_wol(), 9))

            # 4. POLL LOOP
            for _ in range(7):
                await asyncio.sleep(2)
                # Attempt to connect - heartbeat is currently muzzled by WAKING_UP flag
                if await self.connect(timeout=1.0):
                    result = await self.send_command("PWR01")

                    # 5. CLEAR LOCK AND REFRESH UI
                    self._status &= ~ControllerStatus.WAKING_UP
                    if self.on_data_received_callback:
                        self.on_data_received_callback()
                    return result
        except: pass

        # 6. FAIL-SAFE REVERT
        self._status &= ~ControllerStatus.WAKING_UP
        self.transport_state = TascamState.OFF
        if self.on_data_received_callback:
            self.on_data_received_callback()
        return False

    async def power_off(self):
        """Put the unit into standby. send_command() handles the heavy lifting"""
        if self.is_connected:
            await self.send_command("PWR00")

    async def _reset_shutdown_guard(self, delay: int):
        """Give the unit time to shut down gracefully"""
        await asyncio.sleep(delay)
        self._status &= ~ControllerStatus.SHUTTING_DOWN

    # --- INTERNAL ENGINE ---
    async def connect(self, timeout: float = 1.5) -> bool:
        """Try to connect to unit and initialise listener"""
        async with self._connect_lock:
            # GUARD: Prevent duplicate heartbeat tasks
            # We check if it exists AND if it is still running
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(self._heartbeat())

            if self.is_connected:
                return True

            try:
                # Connection attempt
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=timeout
                )
                
                # --- SYNTHESIZED "ON" NOTIFICATION ---
                # The socket just opened. The unit is officially 'Network On'.
                if self._subscribers:
                    on_payload = "!7SSTON"
                    for callback, match in list(self._subscribers.items()):
                        if match is None or match in on_payload:
                            callback(on_payload)
                            
                asyncio.create_task(self._listen())
                await self._poll_sequenced()
                return True
            except Exception as e:
                self.writer = self.reader = None
                return False

    async def disconnect(self):
        """Public method to stop heartbeat and close connection."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self._cleanup()

    async def _heartbeat(self):
        """Monitor connection and handle IR/Manual power-offs."""
        # Set the flag as soon as the loop starts
        self._status |= ControllerStatus.HEARTBEAT_RUN
        fail_count = 0
        self._log("HEARTBEAT STARTED")

        try:
            while True:
                # 1. Respect the 15s cooldown
                if (ControllerStatus.SHUTTING_DOWN | ControllerStatus.WAKING_UP) & self.status:
                    await asyncio.sleep(2)
                    continue

                if not self.is_connected:
                    if not await self.connect(timeout=1.0):
                        # This only triggers if we are NOT already OFF.
                        # It prevents the 10-second loop from re-running the logic.
                        if self.transport_state != TascamState.OFF and not (ControllerStatus.WAKING_UP & self.status):
                            self._log("CONNECTION LOST - CLEANING UP")
                            await self._cleanup()
                        self._log("DEVICE OFFLINE - POLLING AGAIN IN 10S")
                        await asyncio.sleep(10)
                        continue
                else:
                    # If poll fails, assume unit turned off via IR/Front Panel
                    if not await self._poll_sequenced():
                        fail_count += 1
                        self._log(f"POLL FAILED (ATTEMPT {fail_count}/2)")

                        if fail_count >= 2:
                            self._log("MANUAL SHUTDOWN DETECTED")
                            self._status |= ControllerStatus.SHUTTING_DOWN
                            await self._cleanup()
                            asyncio.create_task(self._reset_shutdown_guard(15))
                            fail_count = 0
                        else:
                            await asyncio.sleep(1)
                            continue
                    else:
                        fail_count = 0

                await asyncio.sleep(2)
        finally:
            # Clear the flag if the task is ever cancelled or stops
            self._status &= ~ControllerStatus.HEARTBEAT_RUN
            self._log("HEARTBEAT STOPPED")

    async def _poll_sequenced(self) -> bool:
        """Regularly send a set of requests to the unit"""
        try:
            # If the unit doesn't ACK the first poll, it's effectively OFF
            if not await self.send_command("?SST"): 
                return False
            cmds = ["?MUT", "?MST"]
            if self.is_media_active:
                cmds.extend(["?SET", "?SRT", "?SGN", "?STC", "?STG", "?STT"])

            for cmd in cmds:
                await self.send_command(cmd)
                await asyncio.sleep(0.03)
            return True
        except: return False

    async def send_command(self, cmd_body: str) -> bool:
        """Sends protocol command to unit"""
        # 1. Physical check
        if not self.writer or not self.is_connected:
            return False

        # 2. SHUTDOWN GUARD: Block everything except Power On
        # IF we are already in a shutdown state (flag is set).
        if (ControllerStatus.SHUTTING_DOWN in self.status) and ("PWR01" not in cmd_body):
            self._log(f"COMMAND {cmd_body} BLOCKED: UNIT SHUTTING DOWN.")
            return False

        # 3. EXECUTION
        self.cmd_result = asyncio.get_running_loop().create_future()
        cmd_body = cmd_body.strip()
        full_cmd = cmd_body if cmd_body.startswith("!7") else f"!7{cmd_body}"

        try:
            self.writer.write(f"{full_cmd}\r".encode('ascii'))
            self._log(f"SENT {full_cmd}", False)
            await self.writer.drain()

            # Wait for ACK
            success = await asyncio.wait_for(self.cmd_result, timeout=1.0)

            # 4. POST-SEND LOGIC: Now set the flags AFTER the command is sent
            if "PWR00" in cmd_body and success:
                self._status |= ControllerStatus.SHUTTING_DOWN
                self.transport_state = TascamState.OFF
                if self.on_data_received_callback:
                    self.on_data_received_callback()
                await asyncio.sleep(0.5)
                await self._cleanup()
                asyncio.create_task(self._reset_shutdown_guard(15))

            return success
        
        except asyncio.TimeoutError:
            self._log(f"TIMEOUT - NO RESPONSE FOR {full_cmd}")
            return False
        except Exception as err:
            # This captures the 'nack' exception we set in _handle_response
            self._log(f"COMMAND FAILED: {err}")
            return False

    async def _cleanup(self):
        """Internal reset: Closes sockets and wipes UI data."""
        async with self._cleanup_lock:
            # Now that we are inside the lock, the second task
            # is forced to wait until the first task finishes completely.
            if self.writer is None and self.transport_state == TascamState.OFF:
                return

            if self.writer:
                try:
                    w = self.writer
                    self.writer = self.reader = None
                    w.close()
                    await w.wait_closed()
                except: pass

            self.transport_state = TascamState.OFF
            self._clear_metadata()            
            
            # SYNTHESIZE GLOBAL MESSAGE
            # Manually fire the "OFF" event to all subscribers.
            if self._subscribers:
                off_payload = "!7SSTOFF" # Manually synthesized "Power Off" string
                for callback, match in list(self._subscribers.items()):
                    if match is None or match in off_payload:
                        callback(off_payload)            

            if self.on_data_received_callback:
                self.on_data_received_callback()

            self._log("CLEANUP COMPLETE - DRIVER IDLE")

    async def _listen(self):
        """Listens to responses from the unit (solicited and unsolicited)"""
        try:
            while self.writer and self.reader:
                data = await self.reader.read(4096)
                if not data:
                    break
                
                raw_string = data.decode('ascii', errors='ignore')
                
                # 1. THE HANDSHAKE (unblocks the 'await' in send_command)
                if self.cmd_result and not self.cmd_result.done():
                    low_raw = raw_string.lower()
                    if "ack" in low_raw and "nack" not in low_raw:
                        self.cmd_result.set_result(True)
                    elif "nack" in low_raw or "error" in low_raw:
                        self.cmd_result.set_exception(Exception(f"NACK: {raw_string}"))

                # 2. THE PAYLOAD (updates the UI)
                # We strip the 'ack+' here so the parser only deals with clean !7 commands
                clean_payload = raw_string.strip().replace("ack+", "")
                if "!7" in clean_payload:
                    self._handle_response(clean_payload)
        except Exception as e:
            self._log(f"LISTENER ERROR: {e}")
        finally:
            await self._cleanup()

    def _handle_response(self, raw_data: str):
        """Parse raw TCP response into internal state attributes."""
        self._log(f"RAW DATA RECEIVED: {raw_data}")

        # Global flags for the final Home Assistant UI callback (Step 10)
        state_changed = False
        time_changed = False

        segments = raw_data.split('!7')
        for seg in segments:
            # Skip empty or malformed segments
            if not seg or seg.lower() in ("ack", "nack", "error") or len(seg) < 2:
                continue
            
            # Reset flags for THIS specific segment
            is_monitored = False  
            segment_changed = False
            segment_time_changed = False
            is_transitional = "UNKN" in seg

            # 2. Transport State (SST)
            if seg.startswith("SST"):
                is_monitored = True
                val = seg[3:]
                for code, state_enum in self.PROTOCOL_MAP.items():
                    if code == val:
                        if self.transport_state != state_enum:
                            self.transport_state = state_enum
                            segment_changed = True
                            state_changed = True
                        break

            # 3. Media Status (MST) - Sources and Tray State
            elif seg.startswith("MST"):
                is_monitored = True
                val = seg[3:5]
                try:
                    new_disc_status = TascamDiscState[val]
                    if self.disc_status != new_disc_status:
                        self.disc_status = new_disc_status
                        segment_changed = True
                        state_changed = True
                except KeyError:
                    self.disc_status = TascamDiscState.UF

                # Physical Tray Status
                new_tray_state = (val == "TO")
                if self.tray_open != new_tray_state:
                    self.tray_open = new_tray_state
                    segment_changed = True
                    state_changed = True

            # 4. Mute Status (MUT): 00=Muted, 01=Unmuted
            elif seg.startswith("MUT"):
                is_monitored = True
                new_mute = ("00" in seg)
                if self.is_muted != new_mute:
                    self.is_muted = new_mute
                    segment_changed = True
                    state_changed = True

            # 5. Numeric Metadata with UNKN transition awareness
            elif seg.startswith(("GNMX", "GNM", "GN", "TGNX", "TNM", "TN", "TTN", "TT")):
                is_monitored = True
                if is_transitional:
                    new_val = "0"
                else:
                    raw_val = "".join(filter(str.isdigit, seg))
                    new_val = raw_val.lstrip('0') or "0"

                if seg.startswith(("GNMX", "GNM", "GN")):
                    if self.current_group != new_val:
                        self.current_group = new_val
                        segment_changed = True
                        state_changed = True
                elif seg.startswith("TGNX"):
                    if self.total_groups != new_val:
                        self.total_groups = new_val
                        segment_changed = True
                        state_changed = True
                elif seg.startswith(("TNM", "TN")):
                    if self.current_track != new_val:
                        self.current_track = new_val
                        segment_changed = True
                        state_changed = True
                elif seg.startswith(("TTN", "TT")):
                    if self.total_tracks != new_val:
                        self.total_tracks = new_val
                        segment_changed = True
                        state_changed = True

            # 6. Playback Time (SET = Elapsed, SRT = Remaining)
            elif seg.startswith("SET"):
                is_monitored = True
                new_elapsed = 0 if is_transitional else self._time_to_seconds(seg[3:])
                if self.elapsed_seconds != new_elapsed:
                    self.elapsed_seconds = new_elapsed
                    segment_time_changed = True
                    time_changed = True
            elif seg.startswith("SRT"):
                is_monitored = True
                new_remaining = 0 if is_transitional else self._time_to_seconds(seg[3:])
                if self.remaining_seconds != new_remaining:
                    self.remaining_seconds = new_remaining
                    segment_time_changed = True
                    time_changed = True

            # 7. Notify matching subscribers (Inside the loop for atomic reporting)
            if self._subscribers:
                # Fire if:
                # A) It is a Discovery command (not monitored)
                # B) It is a monitored command that changed state
                # C) It is NOT a routine time update (to avoid 1-sec flood)
                if (not is_monitored or segment_changed) and not segment_time_changed:
                    full_command = f"!7{seg}"
                    for callback, match in list(self._subscribers.items()):
                        if match is None or match in full_command:
                            callback(full_command)

        # 8. Post-Parsing Logic: Total Time Calculation
        if time_changed and self.elapsed_seconds > 0 and self.remaining_seconds > 0:
            self.total_seconds = self.elapsed_seconds + self.remaining_seconds

        # 9. Lifecycle Guard: Clear metadata if unit is off or media is inactive
        if not self.is_media_active or self.transport_state == TascamState.OFF:
            if self.elapsed_seconds != 0 or self.current_track != "0":
                self._clear_metadata()
                state_changed = True

        # 10. Final Callback to Home Assistant UI Entities
        if (state_changed or time_changed) and self.on_data_received_callback:
            self.on_data_received_callback()

    def _clear_metadata(self):
        """Reset all track, group, and time data to default values."""
        # Reset strings to "0" or "Unknown"
        self.current_group = self.total_groups = "0"
        self.current_track = self.total_tracks = "0"

        # Reset integers to 0 so progress bars in the UI drop to zero
        self.elapsed_seconds = self.remaining_seconds = self.total_seconds = 0

        # Reset Enums/Booleans
        self.disc_status = TascamDiscState.NC
        self.tray_open = False

        # Note: transport_state is handled by the calling function (_cleanup)
        # to ensure we don't create a recursive loop.

        self._log("METADATA CLEARED")

    def _time_to_seconds(self, tascam_time: str) -> int:
        """Helper to conver raw seconds into 000:00:00"""
        match = re.search(r'(\d{3})(\d{2})(\d{2})$', tascam_time)
        if match:
            hhh, mm, ss = map(int, match.groups())
            return (hhh * 3600) + (mm * 60) + ss
        return 0

    def _log(self, message: str, is_status: bool = True):
        """Log debug messages when HA debugging enabled for the integration"""
        prefix = "Status" if is_status else "Command"
        _LOGGER.debug(f"[{self.host}] {prefix}: {message}")
