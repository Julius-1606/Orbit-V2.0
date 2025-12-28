import os
import json
import random
import asyncio
import sys
import time
import warnings
import toml

# --- 🔇 SUPPRESS WARNINGS ---
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"
warnings.filterwarnings("ignore")

import google.generativeai as genai
from telegram import Bot
from github import Github  # Requires: pip install PyGithub

# --- 🔐 SECRETS MANAGEMENT ---
GEMINI_API_KEYS = [] # Initialize explicitly to prevent NameError

# 1. Load Secrets from Env
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
KEYS_STRING = os.environ.get("GEMINI_KEYS")
GITHUB_PAT = os.environ.get("GITHUB_KEYS") or os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")

# 2. Local Fallback (If Env is missing stuff)
if not TELEGRAM_TOKEN or not KEYS_STRING or not GITHUB_PAT:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(script_dir, ".streamlit", "secrets.toml")
        
        if os.path.exists(secrets_path):
            print(f"📂 Loading secrets from: {secrets_path}")
            with open(secrets_path, "r") as f:
                local_secrets = toml.load(f)
                
                TELEGRAM_TOKEN = TELEGRAM_TOKEN or local_secrets.get("TELEGRAM_TOKEN")
                
                # Handle Gemini Keys
                raw_keys = local_secrets.get("GEMINI_KEYS")
                if isinstance(raw_keys, list):
                    GEMINI_API_KEYS = raw_keys
                elif isinstance(raw_keys, str):
                    GEMINI_API_KEYS = [k.strip() for k in raw_keys.split(",")]
                
                GITHUB_PAT = GITHUB_PAT or local_secrets.get("GITHUB_KEYS") or local_secrets.get("GITHUB_TOKEN")
                GITHUB_REPO = GITHUB_REPO or local_secrets.get("GITHUB_REPO")

    except Exception as e:
        print(f"⚠️ Local secrets error: {e}")

# 3. Final Processing
# If GEMINI_API_KEYS is still empty but KEYS_STRING exists (Env var path), parse it
if not GEMINI_API_KEYS and KEYS_STRING:
    GEMINI_API_KEYS = [k.strip() for k in KEYS_STRING.split(",")]

# Final Cleanup (Safe because GEMINI_API_KEYS is initialized)
GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS if k.strip()]

# Validate Critical Secrets
if not TELEGRAM_TOKEN or not GEMINI_API_KEYS:
    print("❌ FATAL ERROR: Telegram Token or Gemini Keys missing.")
    sys.exit(1)

CHAT_ID = "6882899041" 
CURRENT_KEY_INDEX = 0

# --- CONFIGURATION & ROTATION ---
def configure_genai():
    global CURRENT_KEY_INDEX
    if not GEMINI_API_KEYS: return
    key = GEMINI_API_KEYS[CURRENT_KEY_INDEX]
    try:
        genai.configure(api_key=key)
        # print(f"🔑 Active Key Index: {CURRENT_KEY_INDEX}") # Debug only
    except Exception as e:
        print(f"⚠️ Config Error on Key #{CURRENT_KEY_INDEX+1}: {e}")

def rotate_key():
    global CURRENT_KEY_INDEX
    if len(GEMINI_API_KEYS) > 1:
        CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(GEMINI_API_KEYS)
        print(f"🔄 Rotating to Backup Key #{CURRENT_KEY_INDEX + 1}...")
        configure_genai()
        global model
        model = get_valid_model() 
        return True
    return False

# 📡 SONAR SCANNER
def get_valid_model():
    print("🔍 Sonar Scanning for valid models...")
    try:
        models = list(genai.list_models())
        valid_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # 1. Look for standard 1.5 flash
        for m in valid_models:
            if 'gemini-1.5-flash' in m and 'latest' not in m and 'exp' not in m:
                print(f"✅ Locked on target: {m}")
                return genai.GenerativeModel(m.replace("models/", ""))
        
        # 2. Look for ANY flash
        for m in valid_models:
             if 'flash' in m and 'gemini-2' not in m and 'exp' not in m:
                print(f"⚠️ Flash Fallback: {m}")
                return genai.GenerativeModel(m.replace("models/", ""))

        if valid_models:
            return genai.GenerativeModel(valid_models[0].replace("models/", ""))
            
    except Exception as e:
        print(f"⚠️ Scan failed: {e}")
    
    print("🤞 Sonar failed. Forcing 'gemini-1.5-flash'...")
    return genai.GenerativeModel('gemini-1.5-flash')

configure_genai()
model = get_valid_model()

# 🛡️ SAFE GENERATOR
def generate_content_safe(prompt_text):
    global model
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt_text)
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg:
                print("⚠️ Model 404. Re-scanning...")
                model = get_valid_model()
                time.sleep(1)
                continue
            elif "429" in err_msg or "403" in err_msg:
                print(f"⏳ API Issue ({err_msg}). Rotating...")
                if rotate_key():
                    time.sleep(2)
                    continue
                else:
                    time.sleep(10)
            else:
                print(f"❌ API Error: {err_msg}")
                return None
    return None

# 🛡️ TELEGRAM SAFETY VALVE
async def send_safe_message(bot, chat_id, text):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
    except Exception as e:
        print(f"⚠️ HTML Parse Error: {e}. Sending raw text.")
        await bot.send_message(chat_id=chat_id, text=text)

# --- ☁️ CONFIG LOADER (CLOUD SYNCED) ---
def load_config():
    # 1. Try fetching from GitHub (The Cloud Truth)
    if GITHUB_PAT and GITHUB_REPO:
        try:
            print("☁️ Fetching config from GitHub...")
            g = Github(GITHUB_PAT)
            repo = g.get_repo(GITHUB_REPO)
            contents = repo.get_contents("config.json")
            decoded = contents.decoded_content.decode()
            return json.loads(decoded)
        except Exception as e:
            print(f"⚠️ Cloud load failed: {e}. Falling back to local.")

    # 2. Fallback to Local File
    print("📂 Loading local config...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    try:
        with open(config_path, 'r') as f: return json.load(f)
    except FileNotFoundError: return None

async def send_chaos():
    bot = Bot(token=TELEGRAM_TOKEN)
    config = load_config()
    
    if not config:
        print("❌ Config could not be loaded. Aborting mission.")
        return 

    if "--quiz" in sys.argv: roll = 90
    elif "--fact" in sys.argv: roll = 60
    else: roll = random.randint(1, 100)
    print(f"🎲 Rolled a {roll}")

    if roll <= 50:
        print("Silence is golden.")
        return

    # --- FACT MODE ---
    elif 51 <= roll <= 85:
        topic = random.choice(config['interests'])
        prompt = f"Tell me a mind-blowing, short random fact about {topic}. Keep it under 2 sentences."
        response = generate_content_safe(prompt)
        if response and response.text:
            msg = f"🎱 <b>Magic-∞ Fact:</b>\n\n{response.text}"
            await send_safe_message(bot, CHAT_ID, msg)
        else:
            print("⚠️ No response for Fact")

    # --- MULTI-QUIZ MODE ---
    elif 86 <= roll <= 98:
        quotes = [
            "Your stop loss is tighter than your work ethic right now. 🛑💀",
            "Green candles wait for no one. Neither does your rent. 🕯️💸",
            "Market's volatile. Your focus? Non-existent. 📉🥴",
            "Stop staring at the 1-minute chart and start grinding. ⏳😤",
            "Do it for the plot. (And the paycheck). 🎬💰",
            "Standing on business? More like sleeping on business. 🛌📉",
            "Delulu is not the solulu if you don't do the work. 🦄🚫",
            "Academic comeback season starts in 3... 2... never mind, just start. 🎓🏁",
            "Not the academic downfall arc... fix it immediately. 📉🚧",
            "Brain rot is real, and you are patient zero. 🧟📉",
            "Locked in? Or locked out of reality? Focus. 🔒🌍"
        ]
        
        unit = random.choice(config['current_units'])
        quote = random.choice(quotes)
        
        # 🎲 Determine number of questions (1 to 5 to avoid spam bans, adjust to 10 if you want)
        num_q = random.randint(1, 5) 
        
        await send_safe_message(bot, CHAT_ID, f"🚨 <b>{quote}</b>\n\nIncoming Rapid Fire: <b>{num_q} Questions on {unit}</b>")
        
        # BATCH REQUEST: Ask for ALL questions in ONE prompt
        prompt = f"""
        Generate {num_q} multiple-choice questions about {unit} for a 4th Year Student.
        
        Strict JSON format: Return a LIST of objects.
        [
            {{"question": "...", "options": ["A","B","C","D"], "correct_id": 0, "explanation": "..."}},
            ...
        ]
        
        Limits: Question < 250 chars, Options < 100 chars.
        """.replace("{num_questions}", str(num_q)) # Safe replace

        response = generate_content_safe(prompt)
        
        if response and response.text:
            try:
                text = response.text.replace('```json', '').replace('```', '').strip()
                data = json.loads(text)
                
                # Ensure it's a list
                if isinstance(data, dict):
                    data = [data] # Wrap single result in list
                
                # LOOP AND FIRE 🔥
                for i, q in enumerate(data):
                    try:
                        await bot.send_poll(
                            chat_id=CHAT_ID,
                            question=f"[{i+1}/{len(data)}] {q['question'][:290]}",
                            options=[o[:97] for o in q['options']],
                            type="quiz",
                            correct_option_id=q['correct_id'],
                            explanation=q['explanation'][:190]
                        )
                        # Sleep to prevent Telegram flooding (429 Too Many Requests)
                        time.sleep(2) 
                    except Exception as e:
                        print(f"⚠️ Poll {i+1} failed: {e}")
                        
            except Exception as e:
                print(f"Quiz Parse Error: {e}")
        else:
             print("⚠️ No response for Quiz")
             
    else:
        await send_safe_message(bot, CHAT_ID, "👑 <b>GOD MODE ACTIVATED</b>")

if __name__ == "__main__":
    asyncio.run(send_chaos())
