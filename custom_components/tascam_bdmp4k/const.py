from homeassistant.components.media_player import MediaPlayerEntityFeature

DOMAIN = "tascam_bdmp4k"
EVENT_RAW_MESSAGE = f"{DOMAIN}_raw_message"
EVENT_GLOBAL_MESSAGE = f"{DOMAIN}_global_message"
DEFAULT_PORT = 9030
DEFAULT_NAME = "BD-MP4K"

SUPPORT_TASCAM = (
    MediaPlayerEntityFeature.TURN_ON |
    MediaPlayerEntityFeature.TURN_OFF |
    MediaPlayerEntityFeature.PLAY |
    MediaPlayerEntityFeature.PAUSE |
    MediaPlayerEntityFeature.STOP |
    MediaPlayerEntityFeature.PREVIOUS_TRACK |
    MediaPlayerEntityFeature.NEXT_TRACK |
    MediaPlayerEntityFeature.VOLUME_MUTE
)
