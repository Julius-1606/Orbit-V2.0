import os
import warnings
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"
warnings.filterwarnings("ignore")

import streamlit as st
import json
import time
import random
import google.generativeai as genai
from github import Github
from datetime import datetime

# --- ⚙️ SETTINGS ---
MAX_ARCHIVED_SESSIONS = 10 

# --- 🔐 SECURE KEYCHAIN ---
GEMINI_API_KEYS = []
try:
    raw_keys = st.secrets.get("GEMINI_KEYS")
    if raw_keys:
        if isinstance(raw_keys, list):
            GEMINI_API_KEYS = raw_keys
        else:
            GEMINI_API_KEYS = [k.strip() for k in raw_keys.split(",")]
except Exception:
    pass

if not GEMINI_API_KEYS:
    try:
        keys_str = os.environ.get("GEMINI_KEYS")
        if keys_str:
            GEMINI_API_KEYS = [k.strip() for k in keys_str.split(",")]
    except Exception:
        pass

if not GEMINI_API_KEYS:
    st.error("❌ NO API KEYS FOUND! Please configure secrets.")
    st.stop()

if "key_index" not in st.session_state: st.session_state.key_index = 0

# --- 🧠 BRAIN CONFIGURATION (OPTIMIZED) ---
def configure_genai():
    """Sets the active API key based on session state index."""
    try:
        # Wrap index safety
        idx = st.session_state.key_index % len(GEMINI_API_KEYS)
        current_key = GEMINI_API_KEYS[idx]
        genai.configure(api_key=current_key)
        return True
    except Exception: return False

def resolve_model_name():
    """Scans for the best model ONCE and caches it."""
    try:
        configure_genai()
        models = list(genai.list_models())
        valid_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Priority 1: Flash 1.5
        for m in valid_models:
            if 'gemini-1.5-flash' in m and 'latest' not in m and 'exp' not in m:
                return m.replace("models/", "")
        
        # Priority 2: Any Flash
        for m in valid_models:
             if 'flash' in m and 'gemini-2' not in m and 'exp' not in m:
                return m.replace("models/", "")

        # Priority 3: Anything else
        if valid_models:
            return valid_models[0].replace("models/", "")
    except Exception:
        pass
    return "gemini-1.5-flash" # Fallback

# 1. Initialize Model Name (Only once per session)
if "model_name" not in st.session_state:
    with st.spinner("🛰️ Establishing Uplink..."):
        st.session_state.model_name = resolve_model_name()

# 2. Configure & Instantiate (Runs on every rerun)
configure_genai()
model = genai.GenerativeModel(st.session_state.model_name)

def rotate_key():
    """Switches key index and re-instantiates model without re-scanning."""
    if len(GEMINI_API_KEYS) <= 1:
        st.toast("❌ No backup keys available.", icon="🛑")
        return False

    st.session_state.key_index = (st.session_state.key_index + 1) % len(GEMINI_API_KEYS)
    
    # Re-configure global genai with new key
    configure_genai()
    
    # Update global model object
    global model
    model = genai.GenerativeModel(st.session_state.model_name)
    
    st.toast(f"🔄 Swapped to Key #{st.session_state.key_index + 1}", icon="🔑")
    return True

def ask_orbit(prompt):
    global model
    # Retry loop: Try all keys + 1 extra attempt
    max_retries = len(GEMINI_API_KEYS) + 1
    
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except Exception as e:
            err_msg = str(e)
            is_quota = "429" in err_msg or "quota" in err_msg.lower() or "ResourceExhausted" in err_msg
            is_auth = "403" in err_msg or "leaked" in err_msg.lower() or "API key" in err_msg
            
            if is_quota or is_auth:
                 reason = "Quota" if is_quota else "Auth"
                 # st.toast(f"⚠️ Key #{st.session_state.key_index+1} Failed ({reason}). Rotating...", icon="🔥")
                 if rotate_key():
                    time.sleep(1) # Short breather
                    continue
                 else:
                    return None
            
            # Non-critical error (Server side 500 etc)
            print(f"❌ Chat Error: {err_msg}")
            # Optional: retry once for server errors without rotating
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
                
            return None
    return None

# --- PAGE SETUP ---
st.set_page_config(page_title="Orbit Command Center", page_icon="🛰️", layout="wide")

# --- ☁️ GITHUB INTEGRATION ---
def get_github_session():
    token = st.secrets.get("GITHUB_TOKEN") or st.secrets.get("GITHUB_KEYS")
    repo_name = st.secrets.get("GITHUB_REPO")
    
    if not token or not repo_name:
        st.sidebar.error("❌ GitHub Secrets Missing!")
        return None, None
    
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        return g, repo
    except Exception as e:
        st.sidebar.error(f"❌ GitHub Connection Failed: {e}")
        return None, None

def load_config():
    g, repo = get_github_session()
    if repo:
        try:
            contents = repo.get_contents("config.json")
            decoded = contents.decoded_content.decode()
            return json.loads(decoded)
        except Exception as e:
            st.warning(f"⚠️ Cloud load failed ({e}). Checking local...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    try:
        with open(config_path, 'r') as f: return json.load(f)
    except FileNotFoundError: return None

def save_config(new_config):
    g, repo = get_github_session()
    if repo:
        try:
            contents = repo.get_contents("config.json")
            repo.update_file(
                path=contents.path,
                message="🤖 Orbit Session Sync",
                content=json.dumps(new_config, indent=4),
                sha=contents.sha
            )
            return True
        except Exception as e:
            st.error(f"❌ Cloud Save Failed: {e}")
            return False
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'config.json')
        with open(config_path, 'w') as f: json.dump(new_config, f, indent=4)
        st.toast("Local Save Only", icon="💾")
        return True

st.title("🛰️ Orbit: Your Personal Academic Weapon")

# Load config
if 'config' not in st.session_state:
    st.session_state.config = load_config()

config = st.session_state.config

if config:
    with st.sidebar:
        st.header("👤 Commander Profile")
        st.text_input("Username", value=config.get('user_name', 'Commander'), disabled=True)
        st.divider()
        diffs = ["Easy (Review)", "Medium (Standard)", "Hard (Exam Prep)", "Asian Parent Expectations (Extreme)"]
        curr_diff = config.get('difficulty', "Asian Parent Expectations (Extreme)")
        idx = diffs.index(curr_diff) if curr_diff in diffs else 3
        new_diff = st.selectbox("Difficulty Level", diffs, index=idx)
        if new_diff != curr_diff:
            config['difficulty'] = new_diff
            if save_config(config):
                st.session_state.config = config
        st.divider()
        st.header("🎯 Active Loadout")
        for unit in config['current_units']: st.caption(f"• {unit}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["💬 Orbit Chat", "📜 History", "📝 Chaos Quiz", "📚 Curriculum Manager", "🎲 Chaos Settings"])

    # --- TAB 1: ACTIVE CHAT SESSION ---
    with tab1:
        c1, c2 = st.columns([5, 1])
        with c1:
            st.subheader("🧠 Neural Link")
        with c2:
            if st.button("➕ New Chat", use_container_width=True, help="Archive current session and start fresh"):
                current_msgs = st.session_state.messages
                if current_msgs:
                    if 'archived_sessions' not in config: config['archived_sessions'] = []
                    
                    first_user_msg = next((m['content'] for m in current_msgs if m['role'] == 'user'), "Empty Session")
                    summary = (first_user_msg[:40] + '...') if len(first_user_msg) > 40 else first_user_msg
                    
                    session_archive = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "summary": summary,
                        "messages": current_msgs
                    }
                    
                    config['archived_sessions'].insert(0, session_archive)
                    config['archived_sessions'] = config['archived_sessions'][:MAX_ARCHIVED_SESSIONS]
                    config['active_session'] = []
                    
                    save_config(config)
                    st.session_state.config = config
                    st.session_state.messages = []
                    st.rerun()

        if "messages" not in st.session_state:
            st.session_state.messages = config.get('active_session', [])

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("Ask Orbit..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    ctx = f"""
                    You are Orbit. 
                    User studies: {', '.join(config['current_units'])}. 
                    Difficulty: {config['difficulty']}.
                    Current Session Context: {st.session_state.messages[-6:]}
                    Current Question: {prompt}
                    """
                    response_obj = ask_orbit(ctx)
                    
                    if response_obj and response_obj.text:
                        st.markdown(response_obj.text)
                        st.session_state.messages.append({"role": "assistant", "content": response_obj.text})
                        
                        config['active_session'] = st.session_state.messages
                        save_config(config)
                        st.session_state.config = config
                    else:
                        st.error("⚠️ Connection Interrupted.")

    # --- TAB 2: ARCHIVED SESSIONS ---
    with tab2:
        st.subheader("🗂️ Session Archives")
        st.caption(f"Storing last {MAX_ARCHIVED_SESSIONS} completed sessions.")
        
        archives = config.get('archived_sessions', [])
        
        if not archives:
            st.info("No archives found. Finish a chat and hit 'New Chat' to file it here.")
        else:
            for i, session in enumerate(archives):
                label = f"📅 {session['timestamp']} | 📝 {session['summary']}"
                with st.expander(label, expanded=False):
                    for msg in session['messages']:
                        role_icon = "👤" if msg['role'] == "user" else "🛰️"
                        st.markdown(f"**{role_icon} {msg['role'].title()}:** {msg['content']}")
                        st.divider()

    # --- TAB 3: CHAOS QUIZ GENERATOR ---
    with tab3:
        st.subheader("📝 Generated Quiz")
        st.caption("Generates a random number of questions (1-10) for a random unit.")
        
        col_q1, col_q2 = st.columns([1, 3])
        with col_q1:
            if st.button("🎲 Roll for Quiz", use_container_width=True):
                if not config['current_units']:
                    st.error("No units loaded!")
                else:
                    with st.spinner("Generating Chaos..."):
                        target_unit = random.choice(config['current_units'])
                        num_questions = random.randint(1, 10)
                        
                        q_prompt = f"""
                        Generate {num_questions} multiple-choice questions about {target_unit} for a 4th Year Student.
                        Difficulty: {config['difficulty']}.
                        Return ONLY a raw JSON list of objects. No markdown.
                        Format: [{{"q": "...", "o": ["A", "B"], "a": "A", "e": "..."}}]
                        """
                        response = ask_orbit(q_prompt)
                        
                        if response and response.text:
                            try:
                                clean_text = response.text.replace("```json", "").replace("```", "").strip()
                                quiz_data = json.loads(clean_text)
                                st.session_state['quiz_data'] = quiz_data
                                st.session_state['quiz_unit'] = target_unit
                                st.session_state['quiz_answers'] = {} 
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to parse quiz: {e}")
                        else:
                            st.error("AI returned silence.")

        with col_q2:
            if 'quiz_data' in st.session_state:
                st.info(f"**Unit:** {st.session_state['quiz_unit']} | **Questions:** {len(st.session_state['quiz_data'])}")
                with st.form("quiz_form"):
                    for i, q in enumerate(st.session_state['quiz_data']):
                        st.markdown(f"**{i+1}. {q['q']}**")
                        st.session_state['quiz_answers'][i] = st.radio(
                            "Select answer:", q['o'], key=f"q_{i}", index=None, label_visibility="collapsed"
                        )
                        st.divider()
                    
                    if st.form_submit_button("Submit Quiz"):
                        score = 0
                        total = len(st.session_state['quiz_data'])
                        for i, q in enumerate(st.session_state['quiz_data']):
                            user_ans = st.session_state['quiz_answers'].get(i)
                            if user_ans == q['a']:
                                score += 1
                                st.success(f"Q{i+1}: Correct! ✅")
                            else:
                                st.error(f"Q{i+1}: Wrong. Correct: {q['a']}")
                                st.caption(f"ℹ️ {q['e']}")
                        st.metric("Final Score", f"{score}/{total}")
                        if score == total: st.balloons()
            else:
                st.write("No active quiz. Hit the Roll button.")

    with tab4:
        col1, col2 = st.columns(2)
        with col1:
            years = list(config['unit_inventory'].keys())
            if years:
                y = st.selectbox("Year", years)
                if isinstance(config['unit_inventory'][y], dict):
                    sems = list(config['unit_inventory'][y].keys())
                    s = st.selectbox("Semester", sems)
                    avail = config['unit_inventory'][y][s]
                else:
                    avail = config['unit_inventory'][y]
                    s = "General"
                adds = st.multiselect(f"Add from {y}-{s}", avail)
                if st.button("➕ Add"):
                    changed = False
                    for u in adds:
                        if u not in config['current_units']: 
                            config['current_units'].append(u)
                            changed = True
                    if changed:
                        if save_config(config):
                            st.session_state.config = config
                            st.rerun()
        with col2:
            for unit in config['current_units']:
                if st.checkbox(f"Drop {unit}", key=unit):
                    config['current_units'].remove(unit)
                    if save_config(config):
                        st.session_state.config = config
                        st.rerun()

    with tab5:
        curr = st.text_area("Interests", ", ".join(config['interests']))
        if st.button("Update Interests"):
            config['interests'] = [x.strip() for x in curr.split(",")]
            if save_config(config):
                st.session_state.config = config
                st.success("Updated!")
