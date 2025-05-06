# --- Global State (for simplicity in this challenge) ---
# In a production app, consider more robust state management (e.g., Redis, database)
# if handling multiple users or logs concurrently.
CURRENT_LOG_DATA = None
CURRENT_LOG_FILENAME = None
CONVERSATION_HISTORY = [] # Stores tuples of (user_message, bot_response)
