import os
import json
import streamlit as st
from streamlit_oauth import OAuth2Component, StreamlitOauthError
from streamlit_cookies_manager import EncryptedCookieManager

st.title("Google OAuth Integration Test (Refactored)")

# --- Configuration & Secrets ---
# Read secrets from .streamlit/secrets.toml
# Note: Streamlit loads secrets automatically into st.secrets
# We access them safely here
try:
    CLIENT_ID = st.secrets["auth"]["client_id"]
    CLIENT_SECRET = st.secrets["auth"]["client_secret"]
    REDIRECT_URI = st.secrets["auth"]["redirect_uri"]
    AUTHORIZATION_URL = st.secrets["auth"]["authorization_url"]
    TOKEN_URL = st.secrets["auth"]["token_url"]
    COOKIE_PASSWORD = st.secrets["auth"]["cookie_secret"]
except Exception as e:
    st.error(f"Missing secrets in .streamlit/secrets.toml: {e}")
    st.stop()


# --- Cookie Manager Setup ---
# This manages encrypted cookies to persist session
cookies = EncryptedCookieManager(
    prefix="streamlit_oauth_app/",  # Prefix for cookies
    password=COOKIE_PASSWORD, 
)

if not cookies.ready():
    # Wait for the component to load and send initial data.
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
    # Clear cookies and session state
    if 'token' in st.session_state:
        del st.session_state['token']
    
    # Force update cookie to empty string before save
    cookies['token'] = ""  
    cookies.save()
    st.query_params.clear()
    st.rerun()

# 1. Check if token exists in session state or cookies
if 'token' not in st.session_state:
    # Attempt to load token from cookies
    cookie_token = cookies.get('token')
    if cookie_token:
        try:
            st.session_state['token'] = json.loads(cookie_token)
        except json.JSONDecodeError:
            st.session_state['token'] = None
    else:
        st.session_state['token'] = None

# 2. If valid token exists, show content
if st.session_state['token']:
    st.success("You are logged in!")
    token = st.session_state['token']
    
    # Optional: Display token info or user email if you fetch it
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
        # Serialize to JSON string before saving to cookie
        cookies['token'] = json.dumps(token) 
        cookies.save()
        st.rerun()
