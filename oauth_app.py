import os
import json
import streamlit as st
from streamlit_oauth import OAuth2Component, StreamlitOauthError

st.title("Google OAuth Integration Test")

# --- Configuration & Secrets ---
try:
    CLIENT_ID = st.secrets["auth"]["client_id"]
    CLIENT_SECRET = st.secrets["auth"]["client_secret"]
    REDIRECT_URI = st.secrets["auth"]["redirect_uri"]
    AUTHORIZATION_URL = st.secrets["auth"]["authorization_url"]
    TOKEN_URL = st.secrets["auth"]["token_url"]
except Exception as e:
    st.error(f"Missing secrets in .streamlit/secrets.toml: {e}")
    st.stop()

# --- OAuth Component Setup ---
oauth2 = OAuth2Component(
    CLIENT_ID, 
    CLIENT_SECRET, 
    AUTHORIZATION_URL, 
    TOKEN_URL, 
    TOKEN_URL, 
    ""
)

# --- Main Logic ---

def logout():
    if 'token' in st.session_state:
        del st.session_state['token']
    st.query_params.clear()
    st.rerun()

# 1. Check if token exists in session state
if 'token' not in st.session_state:
    st.session_state['token'] = None

# 2. If valid token exists, show content
if st.session_state['token']:
    st.success("You are logged in!")
    token = st.session_state['token']
    st.json(token)
    
    if st.button("Logout"):
        logout()

# 3. If no token, show login button
else:
    try:
        token = oauth2.authorize_button(
            name="Login with Google",
            icon="https://www.google.com.tw/favicon.ico",
            redirect_uri=REDIRECT_URI,
            scope="openid email profile",
            key="google_oauth_btn",
            extras_params={"prompt": "consent", "access_type": "offline"}
        )
    except StreamlitOauthError:
        st.warning("OAuth state mismatch. Please try again.")
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"OAuth Error: {e}")
        token = None

    # 4. Handle conversion from redirect return to session
    if token:
        st.session_state['token'] = token
        st.rerun()
