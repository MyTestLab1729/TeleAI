import telebot
import requests
import time
from datetime import datetime
import re

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

# ==== GEMINI ====
def ask_gemini(prompt):
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(GEMINI_URL, headers=HEADERS_GEMINI, json=payload)
        res.raise_for_status()
        raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
        # Return the raw text without escaping to preserve Markdown formatting
        return raw_text
    except Exception as e:
        # Escape only the error message to avoid breaking Markdown
        return escape_markdown(f"❌ Gemini error: {str(e)}")

# ==== STABILITY FUNCTIONS ====
def generate_image(prompt):
    url = "https://api.stability.ai/v2beta/stable-image/generate/ultra"
    headers = {
        "authorization": f"Bearer {STABILITY_API_KEY}",
        "accept": "image/*"
    }
    data = {"prompt": prompt, "output_format": "webp"}
    try:
        response = requests.post(url, headers=headers, files={"none": ''}, data=data)
        if response.status_code == 200:
            with open("generated_image.webp", 'wb') as file:
                file.write(response.content)
            return "generated_image.webp"
        return None
    except Exception as e:
        print("Image generation error:", e)
        return None

def get_stability_credits():
    url = "https://api.stability.ai/v1/user/balance"
    headers = {"Authorization": f"Bearer {STABILITY_API_KEY}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            credits = response.json().get("credits", None)
            return round(credits, 2) if credits is not None else "Unknown"
        return None
    except Exception as e:
        print("Credit check error:", e)
        return None

def send_image_for_video(image_path):
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
    for attempt in range(10):
        response = requests.get(result_url, headers=headers)
        if response.status_code == 202:
            bot.edit_message_text("⏳ Still generating...", chat_id, status_msg.message_id)
            time.sleep(6)
        elif response.status_code == 200:
            with open("output_video.mp4", 'wb') as video_file:
                video_file.write(response.content)
            return "output_video.mp4"
        else:
            break
    return None

def generate_audio(prompt, duration):
    url = "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio"
    headers = {"authorization": f"Bearer {STABILITY_API_KEY}", "accept": "audio/*"}
    data = {"prompt": prompt, "output_format": "mp3", "duration": duration, "steps": 30}
    response = requests.post(url, headers=headers, files={"none": ''}, data=data)
    if response.status_code == 200:
        with open("generated_audio.mp3", 'wb') as file:
            file.write(response.content)
        return "generated_audio.mp3"
    return None

# ==== TELEGRAM HANDLERS ====
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, escape_markdown(
        "👋 Welcome to your AI Assistant!\n\n"
        "🤖 Chat: Ask me anything using natural language.\n"
        "🖼️ Image: /imagine A cat playing guitar\n"
        "🎬 Video from Image: Send an image, then type /videofy\n"
        "🎧 Text to Audio: /text2audio 20 Calm ambient music\n"
        "💳 Check Credits: /credits\n\n"
        "Need help? Just ask!"), parse_mode="MarkdownV2")

@bot.message_handler(commands=['imagine'])
def image_command(message):
    prompt = message.text.replace("/imagine", "").strip()
    if not prompt:
        bot.reply_to(message, "Please provide a prompt. Example:\n/imagine A futuristic cityscape at sunset")
        return
    bot.send_chat_action(message.chat.id, 'upload_photo')
    bot.reply_to(message, f"🎨 Generating image for: *{escape_markdown(prompt)}*", parse_mode="MarkdownV2")
    file_path = generate_image(prompt)
    if file_path:
        with open(file_path, "rb") as img_file:
            bot.send_photo(message.chat.id, img_file)
    else:
        bot.reply_to(message, "❌ Failed to generate image. Please try again later.")

@bot.message_handler(commands=['credits'])
def credits_command(message):
    bot.send_chat_action(message.chat.id, 'typing')
    credits = get_stability_credits()
    if credits is not None:
        bot.reply_to(message, f"💳 *Stability AI Balance:* `{credits}` credits", parse_mode="MarkdownV2")
    else:
        bot.reply_to(message, "⚠️ Failed to retrieve Stability AI credit balance.")

@bot.message_handler(content_types=['photo'])
def handle_image(message):
    bot.send_chat_action(message.chat.id, 'upload_video')
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("input_image.jpg", 'wb') as new_file:
        new_file.write(downloaded_file)
    msg = bot.reply_to(message, "🎬 Starting video generation from image...")
    generation_id = send_image_for_video("input_image.jpg")
    if generation_id:
        video_path = get_video_result(generation_id, msg, message.chat.id)
        if video_path:
            with open(video_path, 'rb') as video_file:
                bot.send_video(message.chat.id, video_file, caption="🎉 Here's your generated video!")
        else:
            bot.send_message(message.chat.id, "❌ Failed to generate video.")
    else:
        bot.send_message(message.chat.id, "❌ Couldn't start video generation.")

@bot.message_handler(commands=['text2audio'])
def text_to_audio(message):
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
    bot.send_chat_action(message.chat.id, 'record_audio')
    bot.reply_to(message, f"🎧 Generating {duration}s audio:\n\n`{escape_markdown(prompt)}`", parse_mode="MarkdownV2")
    audio_path = generate_audio(prompt, duration)
    if audio_path:
        with open(audio_path, 'rb') as audio_file:
            bot.send_audio(message.chat.id, audio_file, caption=f"🎶 Here's your {duration}s audio!")
    else:
        bot.send_message(message.chat.id, "❌ Failed to generate audio. Please try again later.")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_input = message.text
    bot.send_chat_action(message.chat.id, 'typing')
    reply = ask_gemini(user_input)
    send_long_message(message.chat.id, reply)

# ==== START ====
print("🤖 Bot is live with Gemini & Stability AI...")
bot.infinity_polling()