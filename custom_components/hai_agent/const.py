"""Constants for the HA AI Agent integration."""

DOMAIN = "hai_agent"

# Sent as `source` so the container's History tab can tell these conversations from the web chat.
SOURCE = "ha"

# Limits of the container's chat API (contract/chat-api/chat_request.schema.json).
MAX_TEXT_CHARS = 4000
MAX_SESSION_ID_CHARS = 100

# Checking the address and password must be quick; a chat command may need several model calls
# (the container's own limit is six), so it gets a generous total time.
CHECK_TIMEOUT_SECONDS = 10
CHAT_TIMEOUT_SECONDS = 90
