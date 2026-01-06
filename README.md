# Tascam BD-MP4K Home Assistant Integration

A production-grade, asynchronous integration for the **Tascam BD-MP4K** Professional 4K UHD Media Player. This driver is engineered for high-end home cinema control, featuring state-aware logic, intelligent power management, and real-time telemetry via TCP.

## 🛠 Installation

### Option 1: HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **Integrations** > **Custom repositories** (via the ⋮ menu).
3. Paste this Repository URL and select **Integration**.
4. Click **Download** and restart Home Assistant.

### Option 2: Manual Installation
1. Download this repository.
2. Copy the `custom_components/tascam_bdmp4k` folder into your `/config/custom_components/` directory.
3. Restart Home Assistant.

---

## ⚙️ Configuration
The integration supports Home Assistant **Config Flow** for a seamless, UI-driven setup.

1. Navigate to **Settings** > **Devices & Services**.
2. Click **Add Integration** and search for **Tascam BD-MP4K**.
3. Provide the following details:
    * **Host:** Reserved/Static IP address of the Tascam unit.
    * **MAC Address:** Required for Wake-on-LAN (WOL) Power-On.
    * **Port:** Default is `9030`.

---

## 📱 Entities & Platforms

The integration initializes **13 entities** to provide a "Single Pane of Glass" view of your player.

### 1. Media Player (`media_player.bd_mp4k`)
The primary playback interface. It tracks Title/Chapter metadata and provides real-time progress bars.

### 2. Remote (`remote.bd_mp4k`)
A state-aware remote entity that supports standard navigation and raw protocol pass-through.

### 3. Sensors (11 Entities)
| Entity | Data Point | Description |
| :--- | :--- | :--- |
| **Transport Status** | `SST` | Playing, Paused, Stopped, Scanning, etc. |
| **Tray Status** | `MST` | Physical tray state (Open/Closed/Error). |
| **Mute Status** | `MUT` | Hardware-level audio mute state. |
| **Disc Status** | `MST` | Disc, No Disc, Unknown Disc. |
| **Elapsed Time** | `SET` | Playback position in `HH:MM:SS`. |
| **Remaining Time** | `SRT` | Time left in `HH:MM:SS`. |
| **Total Time** | `STT` | Full duration in `HH:MM:SS`. |
| **Current Title** | `GN` | Current Group/Title index. |
| **Total Titles** | `GTM` | Total titles available on media. |
| **Current Chapter** | `TN` | Current Track/Chapter index. |
| **Total Chapters** | `TTM` | Total chapters available on media. |

---

## 🎮 Remote Command Reference
Use the `remote.send_command` service to trigger hardware functions.

| Category | Supported Commands |
| :--- | :--- |
| **Navigation** | `up`, `down`, `left`, `right`, `enter`, `back` |
| **Menus** | `home`, `setup`, `top_menu`, `popup_menu`, `option`, `info` |
| **Transport** | `play`, `stop`, `pause`, `next`, `previous`, `ff`, `rw` |
| **Utility** | `audio`, `subtitle`, `toggle_tray`, `toggle_mute`, `mute_on`, `mute_off` |
| **Power** | `power_on`, `power_off` |

> **Raw Pass-through:** Any command sent via the service that is not in the list above (e.g., `NUM3`) will be passed directly to the hardware via the TCP stream. Refer to the [Tascam Ethernet Protocol Specification](BD-MP4K_RS232C_Ethernet_Protocol_v100.pdf).

---

## ⚡ Automation & Events
This integration exposes the Tascam's internal bus directly to the Home Assistant Event Bus for low-latency automation.

### 1. Service: `tascam_bdmp4k.send_command`
A coordinator-level service that allows you to dispatch any Tascam protocol string or friendly command. 

```yaml
service: tascam_bdmp4k.send_command
data:
  entity_id: media_player.tascam_cinema
  command: "!7DSP" # Toggles the hardware OSD overlay
```

### 2. Service: `tascam_bdmp4k.subscribe_to_message`
A specialized listener. It "watches" for a specific protocol response (a `match`) for a set `duration`.

* **match:** The protocol string to listen for (e.g., `!7SSTPL`).
* **duration:** How long the listener remains active (Defaults to 10 seconds).

```yaml
service: tascam_bdmp4k.subscribe_to_message
data:
  entity_id: media_player.tascam_cinema
  match: "!7SSTPL"
  duration: 10
```

### `tascam_bdmp4k_global_message`
Fires for every status update, including synthesized power events.
* **Use Case:** Instantly dim lights the moment playback starts.
* **Payload:** `{"command": "!7SSTPL"}`

## 🔍 Testing & Diagnostics

You can verify the integration's logic and the hardware's responses using the **Developer Tools** in Home Assistant.

### Testing Actions
1. Navigate to **Developer Tools** > **Actions** (formerly Services).
2. Search for `tascam_bdmp4k.send_command`.
3. Switch to **YAML Mode** and paste the following:

```yaml
action: tascam_bdmp4k.send_command
data:
  command: "!7DSP"
```

4. Click **Perform Action**. Your Tascam unit should toggle its On-Screen Display.

### Monitoring the Protocol (Events)
To see the raw communication in real-time:
1. Navigate to **Developer Tools** > **Events**.
2. In **Listen to events**, type: `tascam_bdmp4k_global_message`
3. Click **Start Listening**.
4. Any command or status update (like a tray opening) will appear here:

```yaml
event_type: tascam_bdmp4k_global_message
data:
  device_id: 01KDP26MGA3BPXR3ZY202ASZMQ
  message: "!7SSTDVHM"
origin: LOCAL
time_fired: "2026-01-06T14:48:11.943575+00:00"
context:
  id: 01KE9WF7X7C2XCJ8EBQK52NR8E
  parent_id: null
  user_id: null
  ```


## 🎨 Dashboard Inspiration
The integration works well with the **Mini Media Player** card. Make sure you install the mini media player and card_mod first via HACS. This renders detailed transport state straight into the media player.

```yaml
type: custom:mini-media-player
entity: media_player.bd_mp4k
name: " "
artwork: cover
hide:
  play_pause: false
  play_stop: false
  volume: true
  volume_level: true
mute_button: true
volume_stateless: true
card_mod:
  style: |
    .entity__info__name::after {
      content: " {{ states('sensor.tascam_transport_state') | upper }}";
      color: var(--accent-color);
      font-weight: bold;
    }
grid_options:
  columns: 12
  rows: 2
```

And here are 2 lovelace grids of nicely laid out buttons:

```yaml
square: true
type: grid
cards:
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: power_on
    name: Power On
    icon: mdi:power
  - show_name: true
    show_icon: true
    type: button
    color: red
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: power_off
    name: Power Off
    icon: mdi:power
  - show_name: true
    show_icon: true
    type: button
    name: Open/Close
    icon: mdi:eject
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: toggle_tray
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: toggle_mute
    name: Mute
    color: none
    icon: mdi:volume-off
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: up
    color: green
    icon: mdi:menu-up
    name: Up
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: popup_menu
    name: Pop Up
    icon: mdi:dots-horizontal
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: left
    color: green
    icon: mdi:menu-left
    name: Left
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: enter
    color: green
    icon: mdi:button-pointer
    name: Confirm
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: right
    color: green
    icon: mdi:menu-right
    name: Right
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: back
    icon: mdi:undo
    name: Return
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: down
    color: green
    name: Down
    icon: mdi:menu-down
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: option
    icon: mdi:dots-vertical
    name: Option
```

And grid 2:

```yaml
square: true
type: grid
cards:
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: setup
    icon: mdi:cog
    name: Setup
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: home
    icon: mdi:home-outline
    name: Home
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: info
    icon: mdi:information-outline
    name: Info
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: rw
    icon: mdi:rewind
    name: Rewind
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: play
    icon: mdi:play
    name: Play
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: ff
    name: Forward
    icon: mdi:fast-forward
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: previous
    name: Previous
    icon: mdi:skip-backward
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: pause
    hold_action:
      action: none
    double_tap_action:
      action: none
    name: Pause
    icon: mdi:pause
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: next
    icon: mdi:skip-forward
    name: Next
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: subtitle
    icon: mdi:subtitles
    name: Subtitle
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: stop
    icon: mdi:stop
    name: Stop
  - show_name: true
    show_icon: true
    type: button
    tap_action:
      action: perform-action
      perform_action: remote.send_command
      target:
        entity_id: remote.bd_mp4k
      data:
        command: audio
    name: Audio
    icon: mdi:surround-sound
grid_options:
  columns: 12
  rows: auto
columns: 3
```