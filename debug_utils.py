import logging

logger = logging.getLogger(__name__)

# Debugging utility for state transitions in ConversationHandler
async def debug_state_transition(update, context):
    """
    Logs the current conversation state and user input for debugging purposes.

    Args:
        update (telegram.Update): The current update object.
        context (telegram.ext.CallbackContext): The context object for the conversation.
    """
    current_state = context.user_data.get('current_state', 'UNKNOWN')
    user_input = update.message.text if update.message else "No message"
    logger.debug(f"Current state: {current_state}")
    logger.debug(f"User input: {user_input}")