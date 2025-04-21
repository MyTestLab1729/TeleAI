import telebot
import requests
import time
from datetime import datetime
import re
import os

# ==== CONFIGURATION ====
TELEGRAM_BOT_TOKEN = ''
GEMINI_API_KEY = ''
STABILITY_API_KEY = ''

# ==== CONSTANTS ====
MAX_MESSAGE_LENGTH = 4096

# ==== API ENDPOINTS ====
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
HEADERS_GEMINI = {"Content-Type": "application/json"}

STABILITY_URL = "https://api.stability.ai/v1/generation/stable-diffusion-512-v2-1/text-to-image"
HEADERS_STABILITY = {
    "Authorization": f"Bearer {STABILITY_API_KEY}",
    "Content-Type": "application/json"
}

# ==== UTILS ====
def escape_markdown(text):
    # Split text into parts while preserving code blocks (```)
    parts = re.split(r'(```[\s\S]*?```)', text)
    escaped_parts = []

    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            # Don't escape code blocks
            escaped_parts.append(part)
        else:
            # Escape the markdown special characters
            escape_chars = r'_\*\[\]()~`>#+\-=|{}.!'
            part = re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', part)
            escaped_parts.append(part)

    return ''.join(escaped_parts)

def send_long_message(chat_id, text):
    for i in range(0, len(text), MAX_MESSAGE_LENGTH):
        bot.send_message(chat_id, text[i:i + MAX_MESSAGE_LENGTH])

# ==== STABILITY FUNCTIONS ====
def validate_stability_api_key(api_key):
    """Validate a Stability API key by making a test request."""
    url = "https://api.stability.ai/v1/user/balance"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True  # Key is valid
        elif response.status_code == 401:
            return False  # Key is invalid
        else:
            print(f"Unexpected response while validating Stability API key: {response.status_code}")
            return None  # Other errors (e.g., network issues)
    except Exception as e:
        print(f"Error validating Stability API key: {e}")
        return None  # Network or other errors


def generate_image(prompt, chat_id):
    url = "https://api.stability.ai/v2beta/stable-image/generate/ultra"
    headers = {
        "authorization": f"Bearer {STABILITY_API_KEY}",
        "accept": "image/*"
    }
    data = {"prompt": prompt, "output_format": "webp"}
    file_path = f"{chat_id}_generated_image.webp"
    try:
        response = requests.post(url, headers=headers, files={"none": ''}, data=data)
        if response.status_code == 200:
            with open(file_path, 'wb') as file:
                file.write(response.content)
            return file_path
        return None
    except Exception as e:
        print("Image generation error:", e)
        return None


def get_user_stability_credits(chat_id):
    file_name = f"{chat_id}_stabilityapis.txt"
    if not os.path.exists(file_name):
        return "No API keys found."

    total_credits = 0
    valid_keys = []

    with open(file_name, "r") as file:
        keys = file.readlines()

    for key in keys:
        key = key.strip()
        if not key:
            continue

        url = "https://api.stability.ai/v1/user/balance"
        headers = {"Authorization": f"Bearer {key}"}
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                credits = response.json().get("credits", 0)
                if credits > 5:
                    total_credits += credits
                    valid_keys.append(key)
                else:
                    print(f"API key {key} removed due to low credits ({credits}).")
            else:
                print(f"API key {key} is invalid or failed to fetch credits.")
        except Exception as e:
            print(f"Error checking API key {key}: {e}")

    # Update the file with valid keys only
    with open(file_name, "w") as file:
        file.write("\n".join(valid_keys) + "\n")

    # Set the first valid key as the STABILITY_API_KEY for this user
    global STABILITY_API_KEY
    STABILITY_API_KEY = valid_keys[0] if valid_keys else None

    return total_credits if total_credits > 0 else "No valid API keys with sufficient credits."


def send_image_for_video(image_path, chat_id):
    url = "https://api.stability.ai/v2beta/image-to-video"
    headers = {"authorization": f"Bearer {STABILITY_API_KEY}"}
    files = {"image": open(image_path, "rb")}
    data = {"seed": 0, "cfg_scale": 1.8, "motion_bucket_id": 127}
    response = requests.post(url, headers=headers, files=files, data=data)
    if response.status_code == 200:
        return response.json().get("id")
    return None


def get_video_result(generation_id, status_msg, chat_id):
    result_url = f"https://api.stability.ai/v2beta/image-to-video/result/{generation_id}"
    headers = {"authorization": f"Bearer {STABILITY_API_KEY}", "accept": "video/*"}
    file_path = f"{chat_id}_output_video.mp4"
    for attempt in range(10):
        response = requests.get(result_url, headers=headers)
        if response.status_code == 202:
            bot.edit_message_text("⏳ Still generating...", chat_id, status_msg.message_id)
            time.sleep(6)
        elif response.status_code == 200:
            with open(file_path, 'wb') as video_file:
                video_file.write(response.content)
            return file_path
        else:
            break
    return None


def generate_audio(prompt, duration, chat_id):
    url = "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio"
    headers = {"authorization": f"Bearer {STABILITY_API_KEY}", "accept": "audio/*"}
    data = {"prompt": prompt, "output_format": "mp3", "duration": duration, "steps": 30}
    file_path = f"{chat_id}_generated_audio.mp3"
    try:
        response = requests.post(url, headers=headers, files={"none": ''}, data=data)
        if response.status_code == 200:
            with open(file_path, 'wb') as file:
                file.write(response.content)
            return file_path
        return None
    except Exception as e:
        print("Audio generation error:", e)
        return None


@bot.message_handler(commands=['addCredit'])
def add_credit_command(message):
    msg = bot.reply_to(message, "Please send the new Stability API key.")
    bot.register_next_step_handler(msg, save_user_stability_api_key)


def save_user_stability_api_key(message):
    chat_id = message.chat.id
    new_key = message.text.strip()
    if not new_key:
        bot.reply_to(message, "❌ Invalid API key. Please try again.")
        return

    file_name = f"{chat_id}_stabilityapis.txt"
    with open(file_name, "a") as file:
        file.write(new_key + "\n")

    # Validate the new key
    is_valid = validate_stability_api_key(new_key)
    if is_valid is True:
        bot.reply_to(message, "✅ New Stability API key added successfully!")
    elif is_valid is False:
        # Remove the invalid key
        with open(file_name, "r") as file:
            keys = file.readlines()
        with open(file_name, "w") as file:
            file.writelines([key for key in keys if key.strip() != new_key])
        bot.reply_to(message, "❌ Invalid Stability API key. Please try again.")
    else:
        bot.reply_to(message, "⚠️ Could not validate the API key due to a network issue. Please try again later.")


@bot.message_handler(commands=['credits'])
def credits_command(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'typing')
    total_credits = get_user_stability_credits(chat_id)
    bot.reply_to(message, f"💳 *Total Stability AI Balance:* `{total_credits}` credits", parse_mode="MarkdownV2")


# ==== GEMINI FUNCTIONS ====
def validate_gemini_api_key(api_key):
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": "Test"}]}]}
    try:
        response = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json=payload)
        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            return False
        else:
            print(f"Unexpected response: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error validating Gemini API key: {e}")
        return None

def get_user_gemini_key(chat_id):
    file_name = f"{chat_id}_geminiapis.txt"
    if not os.path.exists(file_name):
        return None
    with open(file_name, "r") as file:
        keys = file.readlines()
    return keys[0].strip() if keys else None

@bot.message_handler(commands=['addGeminiKey'])
def add_gemini_key_command(message):
    msg = bot.reply_to(message, "Please send the new Gemini API key.")
    bot.register_next_step_handler(msg, save_user_gemini_api_key)

def save_user_gemini_api_key(message):
    chat_id = message.chat.id
    new_key = message.text.strip()
    if not new_key:
        bot.reply_to(message, "❌ Invalid API key. Please try again.")
        return
    file_name = f"{chat_id}_geminiapis.txt"
    with open(file_name, "w") as file:
        file.write(new_key + "\n")
    is_valid = validate_gemini_api_key(new_key)
    if is_valid is True:
        bot.reply_to(message, "✅ New Gemini API key added successfully!")
    elif is_valid is False:
        os.remove(file_name)
        bot.reply_to(message, "❌ Invalid Gemini API key. Please try again.")
    else:
        bot.reply_to(message, "⚠️ Could not validate the API key due to a network issue. Please try again later.")

def clean_html_response(html_code):
    # Remove starting ```html and ending ```
    if html_code.strip().startswith("```html"):
        html_code = html_code.strip()[7:]  # remove ```html (7 chars)
    if html_code.strip().endswith("```"):
        html_code = html_code.strip()[:-3]  # remove ending ```
    return html_code.strip()

def ask_gemini(prompt, chat_id):
    gemini_key = get_user_gemini_key(chat_id)
    if not gemini_key:
        return None, "❌ No Gemini API key found. Please add one using /addGeminiKey."
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
    full_prompt = ("Respond in pure HTML format, professionally styled with modern CSS animations with required images and srouces from web embedded beautifully like mordern websites,\
    light/dark mode toggle button beautifully designed, fully responsive layout for mobile and desktop, and an attractive UI. \
    Only output the final HTML code without backticks or markdown blocks. User query: " + prompt)
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    try:
        res = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json=payload)
        if res.status_code == 401:
            return None, "❌ Invalid Gemini API key. Please update it using /addGeminiKey."
        res.raise_for_status()
        raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
        clean_html = clean_html_response(raw_text)
        return clean_html, None
    except Exception as e:
        return None, f"❌ Gemini error: {str(e)}"

# ==== TELEGRAM HANDLERS ====
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, escape_markdown(
        "👋 Welcome to your AI Assistant!\n\n"
        "🤖 Chat: Ask me anything using natural language.\n"
        "🖼️ Image: /imagine A cat playing guitar\n"
        "🎬 Video from Image: Send an image, then type /videofy\n"
        "🎧 Text to Audio: /text2audio 20 Calm ambient music\n"
        "💳 Check Credits: /credits\n"
        "➕ Add Credit: /addCredit\n"
        "🔑 Add Gemini Key: /addGeminiKey\n\n"
        "Need help? Just ask!"), parse_mode="MarkdownV2")


@bot.message_handler(commands=['imagine'])
def image_command(message):
    chat_id = message.chat.id
    prompt = message.text.replace("/imagine", "").strip()
    if not prompt:
        bot.reply_to(message, "Please provide a prompt. Example:\n/imagine A futuristic cityscape at sunset")
        return
    bot.send_chat_action(chat_id, 'upload_photo')
    bot.reply_to(message, f"🎨 Generating image for: *{escape_markdown(prompt)}*", parse_mode="MarkdownV2")
    file_path = generate_image(prompt, chat_id)
    if file_path:
        with open(file_path, "rb") as img_file:
            bot.send_photo(chat_id, img_file)
        os.remove(file_path)  # Delete the file after sending
    else:
        bot.reply_to(message, "❌ Failed to generate image. Please try again later.")


@bot.message_handler(content_types=['photo'])
def handle_image(message):
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, 'upload_video')
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    input_image_path = f"{chat_id}_input_image.jpg"
    with open(input_image_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    msg = bot.reply_to(message, "🎬 Starting video generation from image...")
    generation_id = send_image_for_video(input_image_path, chat_id)
    os.remove(input_image_path)  # Delete the input image after processing
    if generation_id:
        video_path = get_video_result(generation_id, msg, chat_id)
        if video_path:
            with open(video_path, 'rb') as video_file:
                bot.send_video(chat_id, video_file, caption="🎉 Here's your generated video!")
            os.remove(video_path)  # Delete the video after sending
        else:
            bot.send_message(chat_id, "❌ Failed to generate video.")
    else:
        bot.send_message(chat_id, "❌ Couldn't start video generation.")


@bot.message_handler(commands=['text2audio'])
def text_to_audio(message):
    chat_id = message.chat.id
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Please provide a prompt. Example:\n`/text2audio 30 cheerful acoustic music`", parse_mode="MarkdownV2")
        return
    try:
        duration = int(parts[1])
        prompt = parts[2] if len(parts) > 2 else ""
    except ValueError:
        prompt = message.text.replace("/text2audio", "").strip()
        duration = 20
    if not prompt:
        bot.reply_to(message, "❗ Missing audio prompt. Please try again.", parse_mode="MarkdownV2")
        return
    bot.send_chat_action(chat_id, 'record_audio')
    bot.reply_to(message, f"🎧 Generating {duration}s audio:\n\n`{escape_markdown(prompt)}`", parse_mode="MarkdownV2")
    audio_path = generate_audio(prompt, duration, chat_id)
    if audio_path:
        with open(audio_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file, caption=f"🎶 Here's your {duration}s audio!")
        os.remove(audio_path)  # Delete the audio file after sending
    else:
        bot.send_message(chat_id, "❌ Failed to generate audio. Please try again later.")


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    user_input = message.text
    bot.send_chat_action(chat_id, 'typing')
    html_content, error_msg = ask_gemini(user_input, chat_id)
    if error_msg:
        bot.reply_to(message, error_msg)
        return
    if not html_content:
        bot.reply_to(message, "❌ Failed to generate HTML content.")
        return
    dir_name = f"user_{chat_id}"
    os.makedirs(dir_name, exist_ok=True)
    file_path = os.path.join(dir_name, f"{user_input}.html")
    with open(file_path, "w", encoding="utf-8") as html_file:
        html_file.write(html_content)
    with open(file_path, "rb") as doc:
        bot.send_document(chat_id, doc, caption="🌐 Here's your HTML response! 💾")
    os.remove(file_path)
    os.rmdir(dir_name)

# ==== START ====
print("🤖 Bot is live with Gemini & Stability AI...")
bot.infinity_polling()
