import logging
from telegram.error import Forbidden
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, CallbackContext, filters
import gspread
from gspread.exceptions import APIError
from oauth2client.service_account import ServiceAccountCredentials
from telegram import ReplyKeyboardRemove
from httpx import ConnectTimeout
from debug_utils import debug_state_transition
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get the token securely from environment
TOKEN = os.getenv("BOT_TOKEN")


# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets Authentication
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets Authentication - Improved version
try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Get credentials from environment variable
    creds_json = os.environ.get("GOOGLE_CREDS")
    if not creds_json:
        raise ValueError("GOOGLE_CREDS environment variable not set")
    
    creds_dict = json.load(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    
    # Add retry mechanism for connection issues
    client = gspread.Client(auth=creds)
    client.session = gspread.httpsession.HTTPSession(timeout=60)
    client.login()  # Explicit login
    
    # Test connection immediately
    try:
        client.list_spreadsheet_files()
    except Exception as e:
        logger.error(f"Failed to list spreadsheets: {e}")
        raise

except Exception as e:
    logger.error(f"Google Sheets authentication failed: {e}")
    raise


def get_sheet(client, sheet_name):
    try:
        sheet = client.open(sheet_name).sheet1
        # Test access
        sheet.get_all_records()
        return sheet
    except gspread.SpreadsheetNotFound:
        logger.error(f"Spreadsheet '{sheet_name}' not found. Check the name and sharing permissions.")
        raise
    except APIError as e:
        logger.error(f"Google API error accessing '{sheet_name}': {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error accessing '{sheet_name}': {e}")
        raise

# Then initialize your sheets like this:
try:
    student_sheet = get_sheet(client, "students")
    teacher_sheet = get_sheet(client, "teachers")
    results_sheet = get_sheet(client, "resultsnfeedback")
except Exception as e:
    logger.critical("Failed to initialize sheets. Bot cannot start.")
    raise

# Authenticate with Google Sheets
client = gspread.authorize(creds)
student_sheet = client.open("students").sheet1
teacher_sheet = client.open("teachers").sheet1
results_sheet = client.open("resultsnfeedback").sheet1

# Cache for user data
USER_CACHE = {}

# Column indices based on the user's structure
STUDENT_COLUMNS = {
    "first_time": 1,
    "id": 2,
    "full_name": 3,
    "gender": 4,
    "classroom": 5,
    "grade": 6,
    "tuition": 7,
    "subject": 8,
    "password": 9,
    "security_question": 10,
    "security_answer": 11,
}
TEACHER_COLUMNS = {
    "first_time": 1,
    "id": 2,
    "full_name": 3,
    "gender": 4,
    "subject": 5,
    "password": 6,
    "security_question": 7,
    "security_answer": 8,
}

# Conversation states
CHOOSING_ROLE, STUDENT_AUTH, TEACHER_AUTH, PASSWORD_SETUP, PASSWORD_CONFIRM, SECURITY_SETUP, WELCOME_MESSAGE, STUDENT_MENU, TEACHER_MENU, LOG_OUT = range(10)

# Start command with role selection
async def start(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    try:
        logger.info("Received /start command.")
        keyboard = [["Student"], ["Teacher"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

        await update.message.reply_text(
            "🌟 Welcome to X School's official bot! 🌟\n\n"
            "Are you a Student or a Teacher?\n"
            "Please select your role below:",
            reply_markup=reply_markup
        )
        logger.info("Sent welcome message successfully.")
        return CHOOSING_ROLE
    except Exception as e:
        logger.error(f"Error in /start command: {e}")
        return ConversationHandler.END

# Role selection
async def choose_role(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    role = update.message.text.lower()
    logger.info(f"User chose role: {role}")

    if role == "student":
        await update.message.reply_text(
            "📚 Excellent! Please enter your *Student Administration Number* to proceed.",
            parse_mode="Markdown"
        )
        context.user_data['role'] = 'student'
        return STUDENT_AUTH
    elif role == "teacher":
        await update.message.reply_text(
            "👨‍🏫 Welcome, teacher! Please enter your *Teacher ID* to continue.",
            parse_mode="Markdown"
        )
        context.user_data['role'] = 'teacher'
        return TEACHER_AUTH
    else:
        logger.warning("Invalid role selection.")
        await update.message.reply_text(
            "❌ Invalid selection. Please type /start to begin again."
        )
        return ConversationHandler.END


from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# Authenticate user and check for first-time login
# Updated authenticate_user function to handle teacher login flow like student login
# Cache for user data
USER_CACHE = {}


async def authenticate_user(sheet, columns, user_id, role, update, context):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    try:
        # Check if the user is already cached
        if user_id in USER_CACHE:
            user_data = USER_CACHE[user_id]
        else:
            # Find user in the Google Sheet
            cell = sheet.find(user_id)
            if cell:
                row = cell.row
                user_data = sheet.row_values(row)
                USER_CACHE[user_id] = user_data  # Cache the user data
            else:
                logger.warning(f"User ID {user_id} not found in the sheet.")
                await update.message.reply_text(
                    "❌ User not found. Please ensure you are entering the correct ID."
                )
                return STUDENT_AUTH if role == 'student' else TEACHER_AUTH

        # Validate and populate user data from the sheet
        try:
            context.user_data.update({
                'first_time': user_data[columns["first_time"] - 1],
                'user_id': user_id,
                'full_name': user_data[columns["full_name"] - 1],
                'gender': user_data[columns["gender"] - 1],
                'classroom': user_data[columns["classroom"] - 1] if role == 'student' else None,
                'grade': user_data[columns["grade"] - 1] if role == 'student' else None,
                'subject': user_data[columns["subject"] - 1] if role == 'teacher' else None,
                'password': user_data[columns["password"] - 1],
                'security_question': user_data[columns["security_question"] - 1],
                'security_answer': user_data[columns["security_answer"] - 1]
            })
        except IndexError as e:
            logger.error(f"Data missing in Google Sheet for user {user_id}: {e}")
            await update.message.reply_text(
                "❌ Incomplete data found in the system. Please contact support."
            )
            return ConversationHandler.END

        # Handle first-time login
        if context.user_data['first_time'].lower() == "yes":
            logger.info(f"First-time login detected for user {user_id}.")
            await update.message.reply_text(
                "👤 First-time login detected.\n\n"
                "Please set a strong password for your account (4-8 characters):"
            )
            return PASSWORD_SETUP

        # Handle returning user
        else:
            # Add "Forgot Password" inline button
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Forgot Password", callback_data="forgot_password")]
            ])
            logger.info(f"Prompting password for returning user {user_id}.")
            await update.message.reply_text(
                "🔐 Please enter your password to access your account:",
                reply_markup=reply_markup
            )
            return PASSWORD_CONFIRM

    except ConnectTimeout:
        logger.error("Connection timed out while trying to access Google Sheets.")
        await update.message.reply_text(
            "❌ Unable to connect to the server. Please try again later."
        )
        return ConversationHandler.END
    except APIError as e:
        logger.error(f"Google Sheets API error during authentication: {e}")
        await update.message.reply_text(
            "❌ Unable to access data. Please try again later."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error during authentication: {e}")
        await update.message.reply_text(
            "❌ Something went wrong. Please try again later."
        )
        return ConversationHandler.END
# Handle teacher authentication (Teacher ID input)
async def teacher_auth(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    user_id = update.message.text  # Teacher ID entered by the user
    return await authenticate_user(teacher_sheet, TEACHER_COLUMNS, user_id, 'teacher', update, context)

# Confirm Password for Returning Users
async def confirm_password(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    entered_password = update.message.text  # User's entered password
    stored_password = context.user_data.get('password')  # Password from Google Sheet

    # Add "Forgot Password" button
    reply_markup = ReplyKeyboardMarkup(
        [["Forgot Password"]], one_time_keyboard=True, resize_keyboard=True
    )

    if entered_password == stored_password:
        # Password matches, sign the user in
        await update.message.reply_text(
            "✅ Password correct! You are now signed in. Here is your profile:",
            reply_markup=ReplyKeyboardRemove()  # Remove buttons after successful login
        )
        return await welcome_message(update, context)  # Redirect to the welcome message
    else:
        # Password does not match, prompt the user to try again
        await update.message.reply_text(
            "❌ Incorrect password. Please try again:",
            reply_markup=reply_markup  # Ensure the "Forgot Password" button is visible
        )
        return PASSWORD_CONFIRM  # Stay in the PASSWORD_CONFIRM state
    
# Handle first-time user password setup
async def setup_password(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    password = update.message.text
    if 4 <= len(password) <= 8:
        # Temporarily store the password for confirmation
        context.user_data['new_password'] = password
        await update.message.reply_text("✅ Password set! Please re-enter your password to confirm:")
        return "PASSWORD_CONFIRM_SETUP"  # Transition to password confirmation
    else:
        await update.message.reply_text(
            "❌ Password must be between 4 and 8 characters. Please try again:"
        )
        return PASSWORD_SETUP


# Confirm the password for first-time users
async def confirm_setup_password(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    confirm_password = update.message.text
    if confirm_password == context.user_data.get('new_password'):
        # Password confirmation successful
        context.user_data['password'] = confirm_password  # Save the final password
        await update.message.reply_text(
            "✅ Password confirmed! Now, please set a security question for password recovery:"
        )
        return SECURITY_SETUP  # Move to the security question setup
    else:
        # Passwords do not match
        await update.message.reply_text(
            "❌ Passwords do not match. Please set your password again:"
        )
        return PASSWORD_SETUP




# Handle first-time user security question setup
async def setup_security_question(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    if 'security_question' not in context.user_data:
        # Save the security question in user_data
        context.user_data['security_question'] = update.message.text
        await update.message.reply_text("✅ Security question set! Now, please provide the answer:")
        return SECURITY_SETUP
    else:
        # Save the security answer and update the spreadsheet
        context.user_data['security_answer'] = update.message.text
        sheet = student_sheet if context.user_data['role'] == 'student' else teacher_sheet
        columns = STUDENT_COLUMNS if context.user_data['role'] == 'student' else TEACHER_COLUMNS
        user_id = context.user_data['user_id']
        row = sheet.find(user_id).row

        # Update the spreadsheet with the user's information
        sheet.update_cell(row, columns["first_time"], "NO")  # Mark as not first-time
        sheet.update_cell(row, columns["password"], context.user_data['password'])  # Update password
        sheet.update_cell(row, columns["security_question"], context.user_data['security_question'])  # Update security question
        sheet.update_cell(row, columns["security_answer"], context.user_data['security_answer'])  # Update security answer

        # Confirm account creation
        await update.message.reply_text(
            "✅ Your account has been created successfully!\n"
            "Here is your profile:"
        )
        # Automatically display the profile
        return await welcome_message(update, context)


from telegram.ext import CallbackQueryHandler

async def confirm_password(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    if update.callback_query:  # Check if this is a callback from an inline button
        query = update.callback_query
        await query.answer()  # Acknowledge the callback
        if query.data == "forgot_password":
            return await forgot_password_start(update, context)  # Redirect to forgot password flow

    entered_password = update.message.text  # User's entered password
    stored_password = context.user_data.get('password')  # Password from Google Sheet

    # Add "Forgot Password" inline button
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Forgot Password", callback_data="forgot_password")]
    ])

    if entered_password == stored_password:
        # Password matches, sign the user in
        await update.message.reply_text(
            "✅ Password correct! You are now signed in. Here is your profile:",
            reply_markup=ReplyKeyboardRemove()  # Remove buttons after successful login
        )
        return await welcome_message(update, context)  # Redirect to the welcome message
    else:
        # Password does not match, prompt the user to try again
        await update.message.reply_text(
            "❌ Incorrect password. Please try again:",
            reply_markup=reply_markup  # Show "Forgot Password" button
        )
        return PASSWORD_CONFIRM  # Stay in the PASSWORD_CONFIRM state
# Forgot Password Flow

# Step 1: Start Forgot Password Flow
async def forgot_password_start(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    # Check if the update has a message
    if update.message:
        await update.message.reply_text(
            "🔑 Please provide your ID to reset your password:"
        )
        return "FORGOT_PASSWORD_ID"
    # Check if the update is from a callback query
    elif update.callback_query:
        await update.callback_query.answer()  # Acknowledge the callback query
        await update.callback_query.edit_message_text(
            "🔑 Please provide your ID to reset your password:"
        )
        return "FORGOT_PASSWORD_ID"
    else:
        # Log an unexpected case
        logger.warning("forgot_password_start was triggered without a message or callback query.")
        return ConversationHandler.END

# Step 2: Verify User ID and Ask Security Question
async def forgot_password_verify_id(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    user_id = update.message.text
    sheet = student_sheet if context.user_data.get('role') == 'student' else teacher_sheet
    columns = STUDENT_COLUMNS if context.user_data.get('role') == 'student' else TEACHER_COLUMNS

    try:
        cell = sheet.find(user_id)
        if cell:
            row = cell.row
            security_question = sheet.cell(row, columns["security_question"]).value

            context.user_data['reset_user_id'] = user_id
            await update.message.reply_text(
                f"❓ Security Question: {security_question}\n"
                "Please answer the question to proceed:"
            )
            return "FORGOT_PASSWORD_SECURITY"
        else:
            await update.message.reply_text("❌ User ID not found. Please try again.")
            return "FORGOT_PASSWORD_ID"
    except APIError as e:
        logger.error(f"Google Sheets API error during forgot password ID verification: {e}")
        await update.message.reply_text(
            "❌ Unable to access data. Please try again later."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error during forgot password ID verification: {e}")
        await update.message.reply_text(
            "❌ Something went wrong. Please try again later."
        )
        return ConversationHandler.END


# Step 3: Verify Security Answer (Case-Sensitive)
async def forgot_password_verify_security(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    security_answer = update.message.text
    sheet = student_sheet if context.user_data.get('role') == 'student' else teacher_sheet
    columns = STUDENT_COLUMNS if context.user_data.get('role') == 'student' else TEACHER_COLUMNS
    user_id = context.user_data['reset_user_id']

    try:
        cell = sheet.find(user_id)
        if cell:
            row = cell.row
            correct_answer = sheet.cell(row, columns["security_answer"]).value

            # Case-sensitive comparison
            if security_answer == correct_answer:
                await update.message.reply_text(
                    "✅ Security answer verified!\n"
                    "Please set a new password for your account:"
                )
                return "FORGOT_PASSWORD_RESET"
            else:
                await update.message.reply_text("❌ Incorrect answer. Please try again.")
                return "FORGOT_PASSWORD_SECURITY"
    except Exception as e:
        logger.error(f"Error verifying security answer: {e}")
        await update.message.reply_text("❌ Something went wrong. Please try again later.")
        return ConversationHandler.END


# Step 4: Ask for New Password and Confirm
async def forgot_password_reset(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    new_password = update.message.text

    if 'new_password' not in context.user_data:
        # Temporarily store the new password and ask for confirmation
        context.user_data['new_password'] = new_password
        await update.message.reply_text("🔑 Please re-enter your new password to confirm:")
        return "FORGOT_PASSWORD_CONFIRM_RESET"
    else:
        # Confirm the password matches
        if new_password == context.user_data['new_password']:
            # Save the password in the database
            sheet = student_sheet if context.user_data.get('role') == 'student' else teacher_sheet
            columns = STUDENT_COLUMNS if context.user_data.get('role') == 'student' else TEACHER_COLUMNS
            user_id = context.user_data['reset_user_id']

            try:
                cell = sheet.find(user_id)
                if cell:
                    row = cell.row
                    sheet.update_cell(row, columns["password"], new_password)  # Update the password
                    await update.message.reply_text("✅ Your password has been reset successfully!")

                    # Redirect to the role selection
                    return await start(update, context)
            except Exception as e:
                logger.error(f"Error resetting password: {e}")
                await update.message.reply_text("❌ Something went wrong. Please try again later.")
                return ConversationHandler.END
        else:
            # Passwords do not match
            await update.message.reply_text(
                "❌ Passwords do not match. Please set your password again:"
            )
            del context.user_data['new_password']  # Clear the temporary password
            return "FORGOT_PASSWORD_RESET"
async def go_back(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    user_role = context.user_data.get('role', 'student').capitalize()
    logger.info(f"User selected 'Back'. Returning to the {user_role} menu.")

    if user_role == "Student":
        reply_markup = ReplyKeyboardMarkup(
            [["📚 Access Textbooks", "🎥 Watch Video Lessons"], ["🗂️ View Results", "💬 Teacher Feedback"], ["Log Out"]],
            one_time_keyboard=True
        )
        await update.message.reply_text("🔙 Back to the main menu:", reply_markup=reply_markup)
        return STUDENT_MENU

    elif user_role == "Teacher":
        reply_markup = ReplyKeyboardMarkup(
            [["📚 Upload Materials", "📊 View Student Performance"], ["🔙 Back to Role Selection"], ["Log Out"]],
            one_time_keyboard=True
        )
        await update.message.reply_text("🔙 Back to the main menu:", reply_markup=reply_markup)
        return TEACHER_MENU

# Display welcome message
async def welcome_message(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    role = context.user_data['role']
    full_name = context.user_data['full_name']
    gender = context.user_data['gender']
    user_id = context.user_data['user_id']
    grade = context.user_data.get('grade')
    classroom = context.user_data.get('classroom')
    subject = context.user_data.get('subject')

    welcome_text = (
        f"🎉 Welcome, {full_name}!\n\n"
        f"👤 Full Name: {full_name}\n"
        f"🧑 Gender: {gender}\n"
        f"🆔 ID: {user_id}\n"
    )
    if role == "student":
        welcome_text += f"📚 Grade: {grade}\n🛏 Classroom: {classroom}\n\n"
        reply_markup = ReplyKeyboardMarkup(
            [["📚 Access Textbooks", "🎥 Watch Video Lessons"], ["🗂️ View Results", "💬 Teacher Feedback"], ["Log Out"]],
            one_time_keyboard=True
        )
        state = STUDENT_MENU
    else:
        welcome_text += f"📘 Subject: {subject}\n\n"
        reply_markup = ReplyKeyboardMarkup(
            [["📚 Upload Materials", "📊 View Student Performance"], ["🔙 Back to Role Selection"], ["Log Out"]],
            one_time_keyboard=True
        )
        state = TEACHER_MENU

    await update.message.reply_text(
        welcome_text + "What would you like to do?",
        reply_markup=reply_markup
    )
    return state

CHOOSING_ROLE = 0
STUDENT_AUTH = 1
TEACHER_AUTH = 2
STUDENT_MENU = 3
PROVIDE_FEEDBACK = 4

# Define handlers for each state
async def student_menu_handler(update, context):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    await update.message.reply_text("Welcome to the Student Menu!")
    # Add relevant logic here
    return STUDENT_MENU

async def provide_results_feedback(update, context):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    subject = update.message.text
    if subject == "🔙 Back":
        await update.message.reply_text(
            "Returning to the Student Menu...",
            reply_markup=None  # Add appropriate ReplyKeyboardMarkup here
        )
        return STUDENT_MENU  # Ensure this matches the defined state key

    # Handle other logic...
    return PROVIDE_FEEDBACK  # Example of returning another state



# Example implementation for the "Upload Materials" feature
async def upload_materials(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "📤 Please upload the materials you want to share with the students.\n\n"
        "You can upload files such as PDFs, images, or videos. When you're done, type 'Done' or press the 'Back' button.",
        reply_markup=ReplyKeyboardMarkup(
            [["🔙 Back"]], one_time_keyboard=True
        )
    )
    return "UPLOAD_MATERIALS"


# Example implementation for the "View Student Performance" feature
async def view_student_performance(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "📊 Viewing student performance...\n\n"
        "Please select a class or subject to view performance data. When you're done, type 'Done' or press the 'Back' button.",
        reply_markup=ReplyKeyboardMarkup(
            [["🔙 Back"]], one_time_keyboard=True
        )
    )
    return "VIEW_PERFORMANCE"


# Logout confirmation
async def log_out(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    role = context.user_data.get('role', 'user').capitalize()
    logger.info(f"User requested logout. Role: {role}")
    await update.message.reply_text(
        f"🔒 To confirm logout, type '{role} Logout'."
    )
    return "LOG_OUT"


# Updated handle_log_out function
from debug_utils import debug_state_transition

# Logout confirmation
async def handle_log_out(update: Update, context: CallbackContext):
    # Log the state and user input for debugging
    await debug_state_transition(update, context)

    logger.debug(f"Current context.user_data: {context.user_data}")
    user_input = update.message.text
    role = context.user_data.get('role', 'User').capitalize()  # Default to "User" if role is missing
    expected_logout = f"{role} Logout"

    if user_input.strip() == expected_logout:  # Ensure input matches expected format
        # Clear session data
        context.user_data.clear()
        logger.info("User logged out. Session data cleared.")

        # Send logout confirmation and remove buttons
        await update.message.reply_text(
            "✅ Your session has been cleared. You are now logged out.",
            reply_markup=ReplyKeyboardRemove()
        )

        # Provide additional instructions
        await update.message.reply_text(
            "🧹 To clear the visible chat history:\n"
            "- On mobile: Long press the chat and choose 'Clear Chat'.\n"
            "- On desktop: Right-click the chat and select 'Clear History'.\n\n"
            "Restart the bot with /start when you’re ready."
        )

        # Explicitly end the conversation
        return ConversationHandler.END
    else:
        # Invalid input, prompt the user again
        await update.message.reply_text(
            f"❌ Invalid logout confirmation. Please type '{expected_logout}' to confirm."
        )
        return "LOG_OUT"
    

async def access_textbooks(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    logger.info("User accessed the 'Access Textbooks' menu.")
    # Ask the user to choose a subject
    subjects = [["Math", "Science"], ["History", "Literature"], ["🔙 Back"]]
    reply_markup = ReplyKeyboardMarkup(subjects, one_time_keyboard=True)
    await update.message.reply_text(
        "📚 What subject do you want textbooks for?",
        reply_markup=reply_markup
    )
    logger.info("Displayed textbook options. Returning to CHOOSE_TEXTBOOK state.")
    return "CHOOSE_TEXTBOOK"  # Define a new state for choosing the textbook

async def provide_textbook_link(update: Update, context: CallbackContext):
    subject = update.message.text

    if subject == "🔙 Back":
        logger.info("User selected 'Back'. Returning to the main menu.")
        return await go_back(update, context)

    # Generate a random textbook link for the subject
    random_link = f"https://www.google.com/search?q={subject.lower()}+textbook"
    logger.info(f"User selected subject: {subject}. Generated link: {random_link}")
    await update.message.reply_text(
        f"📖 Here are your textbooks for {subject}:\n{random_link}"
    )
    return "CHOOSE_TEXTBOOK"

# Handle "Watch Video Lessons"
async def watch_video_lessons(update: Update, context: CallbackContext):
    # Log the state and user input globally
    await debug_state_transition(update, context)
    # Ask the user to choose a subject for video lessons
    subjects = [["Math", "Science"], ["History", "Literature"], ["🔙 Back"]]
    reply_markup = ReplyKeyboardMarkup(subjects, one_time_keyboard=True)
    await update.message.reply_text(
        "🎥 What subject do you want video lessons for?",
        reply_markup=reply_markup
    )
    return "CHOOSE_VIDEO"  # Define a new state for choosing the video lesson

async def provide_video_link(update: Update, context: CallbackContext):
    subject = update.message.text

    if subject == "🔙 Back":
        logger.info("User selected 'Back'. Returning to the main menu.")
        return await go_back(update, context)
        # Return to the main menu
        

    # Generate a random video lesson link for the subject
    random_link = f"https://www.youtube.com/results?search_query={subject.lower()}+lesson"
    await update.message.reply_text(
        f"🎬 Here are video lessons for {subject}:\n{random_link}"
    )
    return "CHOOSE_VIDEO"  # Stay in the video lesson selection state


# Updated provide_results_feedback function to separate results and feedback
async def provide_results_feedback(update: Update, context: CallbackContext):
    # Log the state and user input for debugging
    await debug_state_transition(update, context)

    logger.debug("Entering provide_results_feedback function.")
    subject = update.message.text
    user_id = context.user_data['user_id']

    # Handle the "🔙 Back" button
    if subject == "🔙 Back":
        # Clear unnecessary keys from context.user_data
        context.user_data.pop('viewing', None)

        # Redirect the user to the appropriate menu
        options = [["📚 Access Textbooks", "🎥 Watch Video Lessons"], ["🗂️ View Results", "💬 Teacher Feedback"], ["Log Out"]]
        reply_markup = ReplyKeyboardMarkup(options, one_time_keyboard=True)
        await update.message.reply_text(
            "🔙 Back to the main menu:",
            reply_markup=reply_markup
        )
        return STUDENT_MENU  # Ensure proper state transition

    # Logic for fetching feedback from Google Sheets
    # Example: Retrieve feedback from `results_sheet`
    try:
        feedback_data = results_sheet.find(user_id)  # Search for user ID in the sheet
        if feedback_data:
            row = feedback_data.row
            feedback_text = results_sheet.cell(row, 2).value  # Adjust column index for feedback
            await update.message.reply_text(
                f"💬 Feedback for {subject}:\n\n{feedback_text}"
            )
        else:
            await update.message.reply_text("❌ No feedback available for this subject.")
    except Exception as e:
        logger.error(f"Error fetching feedback: {e}")
        await update.message.reply_text("❌ Unable to fetch feedback. Please try again later.")

    # Return to the feedback menu
    return STUDENT_MENU


# Updated view_results_feedback function
async def view_results_feedback(update: Update, context: CallbackContext):
     # Log the state and user input for debugging
    await debug_state_transition(update, context)
    user_choice = update.message.text
    if user_choice == "🗂️ View Results":
        context.user_data['viewing'] = 'results'
    elif user_choice == "💬 Teacher Feedback":
        context.user_data['viewing'] = 'feedback'
    else:
        await update.message.reply_text("❌ Invalid choice. Please try again.")
        return "STUDENT_MENU"

    # Ask the user to choose a subject
    options = [["Math", "Science"], ["History", "Literature"], ["🔙 Back"]]
    reply_markup = ReplyKeyboardMarkup(options, one_time_keyboard=True)
    await update.message.reply_text(
        "📊 What subject do you want to view?",
        reply_markup=reply_markup
    )
    return "CHOOSE_RESULTS"


# Updated ConversationHandler
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        CommandHandler("forgot_password", forgot_password_start)
    ],

    states={
        CHOOSING_ROLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)
        ],
        STUDENT_AUTH: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: authenticate_user(student_sheet, STUDENT_COLUMNS, u.message.text, 'student', u, c))
        ],
        TEACHER_AUTH: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_auth)
        ],
        PASSWORD_SETUP: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)
        ],
        PASSWORD_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_password),
            CallbackQueryHandler(confirm_password)  # Handle inline "Forgot Password" button
        ],
         "FORGOT_PASSWORD_ID": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, forgot_password_verify_id)
        ],
        "FORGOT_PASSWORD_SECURITY": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, forgot_password_verify_security)
        ],
        "FORGOT_PASSWORD_RESET": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, forgot_password_reset)
        ],
        "FORGOT_PASSWORD_CONFIRM_RESET": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, forgot_password_reset)
        ],
        SECURITY_SETUP: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, setup_security_question)
        ],
        WELCOME_MESSAGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, welcome_message)
        ],
        STUDENT_MENU: [
        MessageHandler(filters.Regex("📚 Access Textbooks"), access_textbooks),
        MessageHandler(filters.Regex("🎥 Watch Video Lessons"), watch_video_lessons),
        MessageHandler(filters.Regex("🗂️ View Results"), view_results_feedback),
        MessageHandler(filters.Regex("💬 Teacher Feedback"), view_results_feedback),
        MessageHandler(filters.Regex("Log Out"), log_out),
        MessageHandler(filters.Regex("🔙 Back"), start)  # Back button logic to return to role selection
        ],
        TEACHER_MENU: [
            MessageHandler(filters.Regex("📚 Upload Materials"), upload_materials),
            MessageHandler(filters.Regex("📊 View Student Performance"), view_student_performance),
            MessageHandler(filters.Regex("🔙 Back to Role Selection"), start),
            MessageHandler(filters.Regex("Log Out"), log_out)
        ],
        "UPLOAD_MATERIALS": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, go_back)  # Replace with actual upload handling logic
        ],
        "VIEW_PERFORMANCE": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, go_back)  # Replace with actual performance viewing logic
        ],
        "CHOOSE_TEXTBOOK": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, provide_textbook_link)
        ],
        "CHOOSE_VIDEO": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, provide_video_link)  # New state for video lessons
        ],
        "CHOOSE_RESULTS": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, provide_results_feedback)  # New state for results/feedback
        ],
        "LOG_OUT": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_log_out)  # Log out state
        ],
    },
    fallbacks=[
        CommandHandler("cancel", lambda update, context: update.message.reply_text("Operation canceled.")),
        MessageHandler(filters.ALL, lambda u, c: u.message.reply_text("❌ Invalid input. Please try again.")),
        CallbackQueryHandler(forgot_password_start)  # Ensure callback queries are handled
    ],
)

# Debugging State Transitions
async def debug_state_transition(update: Update, context: CallbackContext):
    context.user_data['current_state'] = context.user_data.get('current_state', "UNKNOWN")
    logger.debug(f"Current state: {context.user_data['current_state']}")
    logger.debug(f"User input: {update.message.text if update.message else 'No message'}")


# Main function
def main():
    bot_token = os.getenv("BOT_TOKEN")  # Get the token from .env file
    application = Application.builder().token(bot_token).build()

  
    application.add_handler(conv_handler)
    logger.info("Starting the bot...")
    application.run_polling()
    
if __name__ == '__main__':
    main()
    

 

