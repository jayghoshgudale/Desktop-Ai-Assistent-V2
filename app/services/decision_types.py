# Categories
CATEGORY_GENERAL = "general"
CATEGORY_REALTIME = "realtime"
CATEGORY_CAMERA = "camera"
CATEGORY_TASK = "task"
CATEGORY_MIXED = "mixed"

# Intents
INTENT_OPEN = "open"
INTENT_PLAY = "play"
INTENT_CAMERA = "camera"
INTENT_OPEN_WEBCAM = "open webcam"
INTENT_CLOSE_WEBCAM = "close webcam"
INTENT_GENERATE_IMAGE = "generate image"
INTENT_CONTENT = "content"
INTENT_GOOGLE_SEARCH = "google search"
INTENT_YOUTUBE_SEARCH = "youtube search"
INTENT_CHAT = "chat"
INTENT_OPEN_APP = "open app"
INTENT_CLOSE_APP = "close app"
INTENT_SYSTEM_CONTROL = "system control"
INTENT_SCREEN_VISION = "screen vision"
INTENT_READ_FILE = "read file"
INTENT_RUN_CODE = "run code"
INTENT_CALENDAR = "calendar"
INTENT_LIST_DIR = "list directory"

# Intent Groups
HEAVY_INTENTS = {
    INTENT_GENERATE_IMAGE,
    INTENT_CONTENT
}

INSTANT_INTENTS = {
    INTENT_OPEN,
    INTENT_PLAY,
    INTENT_CAMERA,
    INTENT_OPEN_WEBCAM,
    INTENT_CLOSE_WEBCAM,
    INTENT_GOOGLE_SEARCH,
    INTENT_YOUTUBE_SEARCH,
    INTENT_OPEN_APP,
    INTENT_CLOSE_APP,
    INTENT_SYSTEM_CONTROL,
    INTENT_SCREEN_VISION,
    INTENT_READ_FILE,
    INTENT_RUN_CODE,
    INTENT_CALENDAR,
    INTENT_LIST_DIR,
}

# Routing Map
ROUTE_TO_INTENT = {
    "open": INTENT_OPEN,
    "play": INTENT_PLAY,
    "camera": INTENT_CAMERA,
    "open_webcam": INTENT_OPEN_WEBCAM,
    "close_webcam": INTENT_CLOSE_WEBCAM,
    "generate_image": INTENT_GENERATE_IMAGE,
    "content": INTENT_CONTENT,
    "google_search": INTENT_GOOGLE_SEARCH,
    "youtube_search": INTENT_YOUTUBE_SEARCH,
    "open_app": INTENT_OPEN_APP,
    "close_app": INTENT_CLOSE_APP,
    "system_control": INTENT_SYSTEM_CONTROL,
    "screen_vision": INTENT_SCREEN_VISION,
    "read_file": INTENT_READ_FILE,
    "run_code": INTENT_RUN_CODE,
    "calendar": INTENT_CALENDAR,
    "list_dir": INTENT_LIST_DIR,
    "general": INTENT_CHAT,
    "realtime": INTENT_CHAT,
}