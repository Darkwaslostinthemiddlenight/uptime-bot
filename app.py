import telebot
from telebot import types
import requests
import time
import threading
import schedule
from datetime import datetime

# Initialize Telegram Bot
bot = telebot.TeleBot("8039732483:AAELszNcgl0saq6LKVAT0Dr5rPZJEPEi2Q4")

# Firebase Configuration
FIREBASE_BASE_URL = "https://bkldost-default-rtdb.firebaseio.com"
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

# States for conversation handler
NAME, URL, INTERVAL = range(3)
user_data = {}

# ====================== FIREBASE UTILITY FUNCTIONS ======================

def read_firebase(path, default=None):
    url = f"{FIREBASE_BASE_URL}/{path}.json"
    for attempt in range(MAX_RETRIES):
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return res.json() if res.json() is not None else default
            elif res.status_code == 404:
                return default
        except requests.exceptions.RequestException as e:
            print(f"Firebase read error ({path}) attempt {attempt + 1}: {str(e)}")
        time.sleep(RETRY_DELAY)
    return default

def write_firebase(path, data, merge=False):
    url = f"{FIREBASE_BASE_URL}/{path}.json"
    if merge:
        url += "?print=silent"
    
    method = requests.patch if merge else requests.put
    
    for attempt in range(MAX_RETRIES):
        try:
            res = method(url, json=data, timeout=10)
            if res.status_code in [200, 204]:
                return True
        except requests.exceptions.RequestException as e:
            print(f"Firebase write error ({path}) attempt {attempt + 1}: {str(e)}")
        time.sleep(RETRY_DELAY)
    return False

def update_firebase(path, updates):
    return write_firebase(path, updates, merge=True)

# ====================== BOT FUNCTIONS ======================

# Keyboard layouts
def create_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Login"), types.KeyboardButton("Register"))
    return markup

def create_monitor_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Add Monitor"), types.KeyboardButton("My Monitors"))
    return markup

# Start command
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Welcome to Monitor Bot!", reply_markup=create_main_keyboard())

# Handle main menu options
@bot.message_handler(func=lambda message: message.text in ["Login", "Register"])
def handle_main_menu(message):
    if message.text == "Login":
        msg = bot.send_message(message.chat.id, "Please enter your username:")
        bot.register_next_step_handler(msg, process_username_step)
    else:
        msg = bot.send_message(message.chat.id, "Let's register! Please enter a username:")
        bot.register_next_step_handler(msg, process_register_username_step)

def process_username_step(message):
    username = message.text
    user = read_firebase(f'users/{username}')
    if user:
        msg = bot.send_message(message.chat.id, "Please enter your password:")
        bot.register_next_step_handler(msg, process_password_step, username)
    else:
        bot.send_message(message.chat.id, "Username not found. Please register first.", reply_markup=create_main_keyboard())

def process_password_step(message, username):
    password = message.text
    user = read_firebase(f'users/{username}')
    if user and user.get('password') == password:
        bot.send_message(message.chat.id, f"Welcome back, {username}!", reply_markup=create_monitor_keyboard())
        user_data[message.chat.id] = {'username': username}
    else:
        bot.send_message(message.chat.id, "Incorrect password. Please try again.", reply_markup=create_main_keyboard())

def process_register_username_step(message):
    username = message.text
    user = read_firebase(f'users/{username}')
    if user:
        bot.send_message(message.chat.id, "Username already exists. Please choose another one.", reply_markup=create_main_keyboard())
    else:
        msg = bot.send_message(message.chat.id, "Please enter a password:")
        bot.register_next_step_handler(msg, process_register_password_step, username)

def process_register_password_step(message, username):
    password = message.text
    user_data = {
        'password': password,
        'monitors': {},
        'chat_id': message.chat.id  # Store chat ID for notifications
    }
    if write_firebase(f'users/{username}', user_data):
        bot.send_message(message.chat.id, "Registration successful! You can now login.", reply_markup=create_main_keyboard())
    else:
        bot.send_message(message.chat.id, "Registration failed. Please try again.", reply_markup=create_main_keyboard())

# Handle monitor options
@bot.message_handler(func=lambda message: message.text in ["Add Monitor", "My Monitors"])
def handle_monitor_options(message):
    if message.chat.id not in user_data:
        bot.send_message(message.chat.id, "Please login first.", reply_markup=create_main_keyboard())
        return
        
    if message.text == "Add Monitor":
        msg = bot.send_message(message.chat.id, "Enter a name for your monitor:")
        bot.register_next_step_handler(msg, process_monitor_name_step)
    else:
        show_user_monitors(message)

def process_monitor_name_step(message):
    user_data[message.chat.id]['monitor_name'] = message.text
    msg = bot.send_message(message.chat.id, "Enter the URL to monitor:")
    bot.register_next_step_handler(msg, process_monitor_url_step)

def process_monitor_url_step(message):
    user_data[message.chat.id]['monitor_url'] = message.text
    msg = bot.send_message(message.chat.id, "Enter the check interval in minutes:")
    bot.register_next_step_handler(msg, process_monitor_interval_step)

def process_monitor_interval_step(message):
    try:
        interval = int(message.text)
        username = user_data[message.chat.id]['username']
        monitor_name = user_data[message.chat.id]['monitor_name']
        monitor_url = user_data[message.chat.id]['monitor_url']
        
        monitor_data = {
            'url': monitor_url,
            'interval': interval,
            'last_status': 'Not checked yet',
            'last_checked': 'Never',
            'uptime': 0,
            'downtime': 0
        }
        
        if write_firebase(f'users/{username}/monitors/{monitor_name}', monitor_data):
            bot.send_message(message.chat.id, f"Monitor '{monitor_name}' added successfully!", reply_markup=create_monitor_keyboard())
            start_monitoring(username, monitor_name, monitor_url, interval, message.chat.id)
        else:
            bot.send_message(message.chat.id, "Failed to save monitor. Please try again.", reply_markup=create_monitor_keyboard())
    except ValueError:
        bot.send_message(message.chat.id, "Please enter a valid number for the interval.")

def show_user_monitors(message):
    username = user_data[message.chat.id]['username']
    monitors = read_firebase(f'users/{username}/monitors', {})
    
    if not monitors:
        bot.send_message(message.chat.id, "You don't have any monitors yet.", reply_markup=create_monitor_keyboard())
        return
    
    response = "Your Monitors:\n\n"
    for name, data in monitors.items():
        response += f"🔹 {name}\nURL: {data['url']}\nInterval: {data['interval']} mins\nStatus: {data['last_status']}\nLast Checked: {data['last_checked']}\n\n"
    
    bot.send_message(message.chat.id, response, reply_markup=create_monitor_keyboard())

def check_url(url):
    try:
        response = requests.get(url, timeout=10)
        return "🟢 UP" if response.status_code == 200 else "🔴 DOWN"
    except:
        return "🔴 DOWN"

def start_monitoring(username, monitor_name, url, interval_minutes, chat_id):
    def monitor_job():
        status = check_url(url)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        monitor_path = f'users/{username}/monitors/{monitor_name}'
        monitor_data = read_firebase(monitor_path, {})
        
        # Update statistics
        if status == "🟢 UP":
            monitor_data['uptime'] = monitor_data.get('uptime', 0) + 1
        else:
            monitor_data['downtime'] = monitor_data.get('downtime', 0) + 1
        
        # Check for status change
        old_status = monitor_data.get('last_status')
        monitor_data['last_status'] = status
        monitor_data['last_checked'] = now
        
        if update_firebase(monitor_path, monitor_data):
            if old_status and old_status != status:
                bot.send_message(chat_id, f"Status changed for {monitor_name}:\n{old_status} → {status}")
    
    # Schedule the job
    schedule.every(interval_minutes).minutes.do(monitor_job)
    
    # Run scheduler in background
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    threading.Thread(target=run_scheduler, daemon=True).start()

# Start the bot
print("Bot is running...")
bot.infinity_polling()
