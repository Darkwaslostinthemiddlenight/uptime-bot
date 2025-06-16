import telebot
from telebot import types
import requests
import time
import threading
from datetime import datetime
import firebase

# Initialize Firebase
FIREBASE_URL = "https://bkldost-default-rtdb.firebaseio.com/"
firebase = firebase.FirebaseApplication(FIREBASE_URL, None)

# Initialize Telegram Bot
bot = telebot.TeleBot("8039732483:AAELszNcgl0saq6LKVAT0Dr5rPZJEPEi2Q4")

# States for conversation handler
NAME, URL, INTERVAL = range(3)
user_data = {}

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
    # Check if user exists in Firebase
    user = firebase.get('/users', None)
    if user and username in user:
        msg = bot.send_message(message.chat.id, "Please enter your password:")
        bot.register_next_step_handler(msg, process_password_step, username)
    else:
        bot.send_message(message.chat.id, "Username not found. Please register first.", reply_markup=create_main_keyboard())

def process_password_step(message, username):
    password = message.text
    # Verify password from Firebase
    user = firebase.get(f'/users/{username}', None)
    if user and user['password'] == password:
        bot.send_message(message.chat.id, f"Welcome back, {username}!", reply_markup=create_monitor_keyboard())
        # Store current user in temporary storage
        user_data[message.chat.id] = {'username': username}
    else:
        bot.send_message(message.chat.id, "Incorrect password. Please try again.", reply_markup=create_main_keyboard())

def process_register_username_step(message):
    username = message.text
    # Check if username already exists
    user = firebase.get(f'/users/{username}', None)
    if user:
        bot.send_message(message.chat.id, "Username already exists. Please choose another one.", reply_markup=create_main_keyboard())
    else:
        msg = bot.send_message(message.chat.id, "Please enter a password:")
        bot.register_next_step_handler(msg, process_register_password_step, username)

def process_register_password_step(message, username):
    password = message.text
    # Save new user to Firebase
    firebase.put('/users', username, {'password': password, 'monitors': {}})
    bot.send_message(message.chat.id, "Registration successful! You can now login.", reply_markup=create_main_keyboard())

# Handle monitor options
@bot.message_handler(func=lambda message: message.text in ["Add Monitor", "My Monitors"])
def handle_monitor_options(message):
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
        
        # Save monitor to Firebase
        monitor_data = {
            'url': monitor_url,
            'interval': interval,
            'last_status': 'Not checked yet',
            'last_checked': 'Never',
            'uptime': 0,
            'downtime': 0
        }
        
        firebase.put(f'/users/{username}/monitors', monitor_name, monitor_data)
        
        bot.send_message(message.chat.id, f"Monitor '{monitor_name}' added successfully!", reply_markup=create_monitor_keyboard())
        
        # Start monitoring in background
        start_monitoring(username, monitor_name, monitor_url, interval)
        
    except ValueError:
        bot.send_message(message.chat.id, "Please enter a valid number for the interval.")

def show_user_monitors(message):
    if message.chat.id not in user_data:
        bot.send_message(message.chat.id, "Please login first.", reply_markup=create_main_keyboard())
        return
    
    username = user_data[message.chat.id]['username']
    monitors = firebase.get(f'/users/{username}/monitors', None)
    
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

def start_monitoring(username, monitor_name, url, interval_minutes):
    def monitor_job():
        status = check_url(url)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get current monitor data
        monitor_data = firebase.get(f'/users/{username}/monitors/{monitor_name}', None)
        
        # Update statistics
        if status == "🟢 UP":
            monitor_data['uptime'] = monitor_data.get('uptime', 0) + 1
        else:
            monitor_data['downtime'] = monitor_data.get('downtime', 0) + 1
        
        # Update last status
        monitor_data['last_status'] = status
        monitor_data['last_checked'] = now
        
        # Save back to Firebase
        firebase.put(f'/users/{username}/monitors', monitor_name, monitor_data)
        
        # Notify user if status changed
        if 'last_status' in monitor_data and monitor_data['last_status'] != status:
            # You would need to find the user's chat ID here - this is a simplified version
            # In a real implementation, you'd need to store chat IDs with user data
            pass
    
    # Schedule the job
    schedule.every(interval_minutes).minutes.do(monitor_job)
    
    # Run the scheduler in a separate thread
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    threading.Thread(target=run_scheduler, daemon=True).start()

# Start the bot
print("Bot is running...")
bot.infinity_polling()
