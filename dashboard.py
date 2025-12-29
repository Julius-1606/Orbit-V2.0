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

    # --- TAB 1: CHAT (ACTIVE SESSION) ---
    with tab1:
        # Header + New Chat Button Layout
        c1, c2 = st.columns([5, 1])
        with c1:
            st.subheader("🧠 Neural Link")
        with c2:
            if st.button("➕ New Chat", use_container_width=True, help="Wipe memory and start fresh"):
                st.session_state.messages = []
                st.rerun()

        # 1. Initialize Active Chat (Starts Empty for Focus)
        if "messages" not in st.session_state:
            st.session_state.messages = [] 

        # 2. Display Active Chat
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        # 3. Handle New Input
        if prompt := st.chat_input("Ask Orbit..."):
            # Append User Message to Session
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    # Context Injection (Only sends Active Session)
                    ctx = f"""
                    You are Orbit. 
                    User studies: {', '.join(config['current_units'])}. 
                    Difficulty: {config['difficulty']}.
                    Chat Context: {st.session_state.messages[-5:]}
                    Current Question: {prompt}
                    """
                    response_obj = ask_orbit(ctx)
                    
                    if response_obj and response_obj.text:
                        st.markdown(response_obj.text)
                        
                        # Append AI Message to Session
                        st.session_state.messages.append({"role": "assistant", "content": response_obj.text})
                        
                        # --- DUAL SAVE PROTOCOL ---
                        # 1. Update Permanent History Log
                        if 'chat_history' not in config: config['chat_history'] = []
                        config['chat_history'].append({"role": "user", "content": prompt})
                        config['chat_history'].append({"role": "assistant", "content": response_obj.text})
                        
                        # 2. Trim History (Sliding Window on the LOG, not the session)
                        config['chat_history'] = config['chat_history'][-100:]
                        
                        # 3. Save to Cloud/Local
                        save_config(config)
                        st.session_state.config = config 
                    else:
                        st.error("⚠️ Connection Interrupted. Check Keys.")

    # --- TAB 2: HISTORY ARCHIVE ---
    with tab2:
        st.subheader("📜 Archives")
        st.caption(f"Showing last 100 interactions across all sessions.")
        
        history = config.get('chat_history', [])
        if not history:
            st.info("No archives found. Start chatting in the Neural Link.")
        else:
            for msg in reversed(history): # Show newest on top? Or standard bottom? Let's do standard list
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
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
