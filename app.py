import streamlit as st
import pandas as pd
import re
import uuid
import calendar
import hashlib
import os
import io
from datetime import datetime, timedelta, time

# --- CLOUD IMPORTS ---
import json
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.cloud import storage
from googleapiclient.discovery import build
from streamlit_oauth import OAuth2Component

st.set_page_config(page_title="Vagtplan Manager", layout="wide")

# --- KONFIGURATION ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
MONTH_MAP = {
    'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6,
    'juli': 7, 'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}
DANISH_MONTH_NAMES = ["", "Januar", "Februar", "Marts", "April", "Maj", "Juni", "Juli", "August", "September", "Oktober", "November", "December"]
DANISH_WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]

# --- STORAGE MANAGER (GOOGLE CLOUD STORAGE) ---
class CloudStorageManager:
    """Håndterer filer via Google Cloud Storage (Bucket)."""
    
    def __init__(self):
        try:
            # Vi tjekker om secrets findes, ellers deaktiveres cloud storage featuren
            if "gcp_service_account" in st.secrets and "bucket" in st.secrets:
                creds = service_account.Credentials.from_service_account_info(
                    st.secrets["gcp_service_account"]
                )
                self.client = storage.Client(credentials=creds)
                self.bucket_name = st.secrets["bucket"]["name"]
                self.bucket = self.client.bucket(self.bucket_name)
                self.active = True
            else:
                self.active = False
        except Exception as e:
            print(f"Storage Init Error: {e}")
            self.active = False

    def save_file(self, uploaded_file, month, year):
        if not self.active: return "DISABLED", None

        file_bytes = uploaded_file.getvalue()
        current_hash = hashlib.md5(file_bytes).hexdigest()
        
        ext = uploaded_file.name.split('.')[-1]
        filename = f"{year}_{month:02d}_Schedule.{ext}"
        blob = self.bucket.blob(filename)

        if blob.exists():
            existing_bytes = blob.download_as_bytes()
            existing_hash = hashlib.md5(existing_bytes).hexdigest()
            
            if existing_hash == current_hash:
                return "DUPLICATE", filename
            else:
                blob.upload_from_string(file_bytes, content_type=uploaded_file.type)
                return "UPDATED", filename
        else:
            blob.upload_from_string(file_bytes, content_type=uploaded_file.type)
            return "CREATED", filename

# --- CONFIG MANAGER (CSV BASED) ---
class ConfigManager:
    """Læser konfiguration fra lokale CSV filer i repository."""
    def __init__(self):
        self.durations = {}
        self.details = {}
        self.default_duration = {'start': '0800', 'end': '1600'}
        
        # Load direkte fra filer i mappen
        self.load_durations('shift-durations.csv')
        self.load_details('shift-details.csv')

    def load_durations(self, filepath):
        if not os.path.exists(filepath): return
        try:
            # Læs CSV (Assignment;Start;end)
            df = pd.read_csv(filepath, sep=';', keep_default_na=False)
            for _, row in df.iterrows():
                key = str(row[0]).strip().lower()
                # Sikrer 4 cifre (0800)
                start_t = str(row[1]).strip().zfill(4)
                end_t = str(row[2]).strip().zfill(4)
                self.durations[key] = {'start': start_t, 'end': end_t}
            
            if '*default*' in self.durations:
                self.default_duration = self.durations['*default*']
        except Exception as e:
            print(f"Fejl i durations csv: {e}")

    def load_details(self, filepath):
        if not os.path.exists(filepath): return
        try:
            # Læs CSV (Header: ;mandag;tirsdag...)
            df = pd.read_csv(filepath, sep=';', keep_default_na=False)
            
            # Map kolonner til ugedags-indeks (0=Man, 6=Søn)
            day_map = []
            for col in df.columns:
                c = col.lower()
                if 'man' in c: day_map.append(0)
                elif 'tir' in c: day_map.append(1)
                elif 'ons' in c: day_map.append(2)
                elif 'tor' in c: day_map.append(3)
                elif 'fre' in c: day_map.append(4)
                elif 'lør' in c: day_map.append(5)
                elif 'søn' in c: day_map.append(6)
            
            for _, row in df.iterrows():
                key = str(row[0]).strip().lower()
                self.details[key] = {}
                
                # Udfyld detaljer baseret på kolonnerne
                found_days = 0
                for i in range(1, len(row)):
                    if found_days < len(day_map):
                        val = str(row[i]).strip()
                        if val:
                            day_idx = day_map[found_days]
                            self.details[key][day_idx] = val
                        found_days += 1
        except Exception as e:
            print(f"Fejl i details csv: {e}")

    def get_time_rules(self, shift_name):
        s_name = shift_name.lower()
        if s_name in self.durations: return self.durations[s_name]
        
        # Bedste match (Longest Prefix Match)
        best_match = None
        max_len = 0
        for key in self.durations:
            if key == '*default*': continue
            if s_name.startswith(key):
                if len(key) > max_len:
                    max_len = len(key)
                    best_match = self.durations[key]
        return best_match if best_match else self.default_duration

    def get_detail_label(self, shift_name, date_obj):
        s_name = shift_name.lower()
        weekday = date_obj.weekday()
        best_label = None
        max_len = 0
        for key in self.details:
            if s_name.startswith(key):
                if len(key) > max_len:
                    if weekday in self.details[key]:
                        best_label = self.details[key][weekday]
                        max_len = len(key)
        return best_label

# Cacher config så vi ikke genindlæser CSV ved hver interaktion
@st.cache_resource
def get_config():
    return ConfigManager()

config = get_config()
storage_manager = CloudStorageManager()

# --- GOOGLE AUTH ---

# --- GOOGLE AUTH & COOKIES ---

try:
    CLIENT_ID = st.secrets["auth"]["client_id"]
    CLIENT_SECRET = st.secrets["auth"]["client_secret"]
    REDIRECT_URI = st.secrets["auth"]["redirect_uri"]
    TOKEN_URL = st.secrets["auth"]["token_url"]
    AUTHORIZATION_URL = st.secrets["auth"]["authorization_url"]
except Exception as e:
    st.error(f"Secrets Error: {e}")
    st.stop()

oauth2 = OAuth2Component(
    CLIENT_ID, CLIENT_SECRET, AUTHORIZATION_URL, TOKEN_URL, TOKEN_URL, None,
)

def handle_oauth():
    # Check Session State
    if 'credentials' in st.session_state and st.session_state.credentials:
        return build('calendar', 'v3', credentials=st.session_state.credentials)
    return None

# --- PARSING ENGINE ---

def clean_doctor_code(text):
    if not isinstance(text, str) or not text: return ""
    code = text.split(' ')[0]
    return re.sub(r'[(),]', '', code)

def find_month_year(df):
    header_text = df.head(20).astype(str).to_string()
    match = re.search(r"(?P<month>[a-zA-Z]+)[\s\-_]+(?P<year>20\d{2})", header_text, re.IGNORECASE)
    if match and match.group('month').lower() in MONTH_MAP:
        return MONTH_MAP[match.group('month').lower()], int(match.group('year'))
    return datetime.now().month, datetime.now().year

def parse_schedule(file_obj, file_type):
    if 'xls' in file_type:
        df = pd.read_excel(file_obj, header=None)
    else:
        try:
            content = file_obj.getvalue().decode("utf-8", errors='ignore')
            file_obj.seek(0)
        except AttributeError:
            content = file_obj.decode("utf-8", errors='ignore')
            file_obj = io.BytesIO(file_obj)

        sep = ';' if ';' in content.splitlines()[0] else ','
        df = pd.read_csv(file_obj, sep=sep, header=None, keep_default_na=False)

    month, year = find_month_year(df)
    
    date_row_idx = -1
    for idx, row in df.iterrows():
        numerics = [x for x in row if str(x).strip().isdigit() and 1 <= int(x) <= 31]
        if len(numerics) > 5:
            date_row_idx = idx
            break
            
    if date_row_idx == -1: return pd.DataFrame(), month, year

    col_to_date = {} 
    row_vals = df.iloc[date_row_idx]
    
    day_cols = []
    for c_idx in range(len(df.columns)):
        val = str(row_vals[c_idx]).strip()
        if val.isdigit():
            day_cols.append((c_idx, int(val)))

    if not day_cols: return pd.DataFrame(), month, year

    # Find the index where day 1 occurs to mark the start of the target month
    first_one_idx = next((i for i, (c, d) in enumerate(day_cols) if d == 1), 0)

    # Process leading days belonging to the previous month
    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    for i in range(first_one_idx):
        c_idx, day = day_cols[i]
        try:
            col_to_date[c_idx] = datetime(prev_year, prev_month, day).date()
        except: continue

    # Process target month and trailing days
    curr_month, curr_year = month, year
    last_day = 0
    for i in range(first_one_idx, len(day_cols)):
        c_idx, day = day_cols[i]
        if day < last_day:
            curr_month += 1
            if curr_month > 12: curr_month, curr_year = 1, curr_year + 1
        last_day = day
        try:
            col_to_date[c_idx] = datetime(curr_year, curr_month, day).date()
        except: continue

    if not col_to_date: return pd.DataFrame(), month, year
    first_date_col = min(col_to_date.keys())
    
    base_header_cols = list(range(0, first_date_col))
    if base_header_cols:
        df[base_header_cols[0]] = df[base_header_cols[0]].replace('', pd.NA).ffill()

    events = []
    
    for r_idx in range(date_row_idx + 1, len(df)):
        base_label_parts = []
        for c in base_header_cols:
            val = str(df.iloc[r_idx, c]).strip()
            if val and val.lower() not in ['mandag', 'tirsdag', 'nan', 'none']:
                base_label_parts.append(val)
        
        active_label = " - ".join(base_label_parts)
        gap_text_buffer = []

        for c_idx in range(first_date_col, len(df.columns)):
            if c_idx in col_to_date:
                if gap_text_buffer:
                    new_label = " - ".join(gap_text_buffer)
                    active_label = new_label
                    gap_text_buffer = []

                if not active_label: continue
                cell = str(df.iloc[r_idx, c_idx]).strip()
                if not cell or cell.lower() == 'nan': continue
                
                date_obj = col_to_date[c_idx]
                entries = cell.split('/')
                for entry in entries:
                    entry = entry.strip()
                    if not entry: continue
                    doc = clean_doctor_code(entry)
                    if len(doc) >= 2 and not doc.isdigit():
                        
                        final_summary = active_label
                        detail_label = config.get_detail_label(active_label, date_obj)
                        
                        # --- FEATURE: APPEND AMB ---
                        if detail_label:
                            final_summary = f"{detail_label} AMB"
                        
                        rules = config.get_time_rules(active_label)
                        
                        events.append({
                            'Doctor': doc,
                            'Date': date_obj,
                            'Summary': final_summary,
                            'Description': f"Vagt: {active_label}\nNote: {entry}",
                            'Start_Time': rules['start'],
                            'End_Time': rules['end']
                        })
            else:
                val = str(df.iloc[r_idx, c_idx]).strip()
                if val and val.lower() not in ['nan', 'none']:
                    gap_text_buffer.append(val)

    return pd.DataFrame(events), month, year

def generate_ics_string(events_df):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HospitalsVagtplan//DA", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for _, row in events_df.iterrows():
        uid = str(uuid.uuid4())
        dtstamp = datetime.now().strftime('%Y%m%dT%H%M%SZ')
        date_obj = row['Date']
        start_hm = row['Start_Time']
        end_hm = row['End_Time']
        try:
            sh, sm = int(start_hm[:2]), int(start_hm[2:])
            eh, em = int(end_hm[:2]), int(end_hm[2:])
            dt_start = datetime.combine(date_obj, time(sh, sm))
            dt_end = datetime.combine(date_obj, time(eh, em))
            if dt_end < dt_start: dt_end += timedelta(days=1)
            start_str = dt_start.strftime('%Y%m%dT%H%M%S')
            end_str = dt_end.strftime('%Y%m%dT%H%M%S')
            time_block = f"DTSTART:{start_str}\nDTEND:{end_str}"
        except:
            d_str = date_obj.strftime('%Y%m%d')
            time_block = f"DTSTART;VALUE=DATE:{d_str}"
        status = "TRANSP:TRANSPARENT" if "fri" in str(row['Summary']).lower() else "TRANSP:OPAQUE"
        lines.extend([
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{dtstamp}", time_block,
            f"SUMMARY:{row['Summary']}", f"DESCRIPTION:{row['Description']}", status, "END:VEVENT"
        ])
    lines.append("END:VCALENDAR")
    return "\n".join(lines)

def render_calendar_html(doctor_df):
    if doctor_df.empty: return "<div>Ingen vagter fundet.</div>"
    first_date = doctor_df.iloc[0]['Date'] 
    year, month = first_date.year, first_date.month
    shifts_map = {}
    for _, row in doctor_df.iterrows():
        d = row['Date']
        if d.month == month:
            day = d.day
            if day not in shifts_map: shifts_map[day] = []
            s_t = row['Start_Time']
            e_t = row['End_Time']
            time_lbl = f"{s_t[:2]}:{s_t[2:]}-{e_t[:2]}:{e_t[2:]}"
            shifts_map[day].append(f"{time_lbl} {row['Summary']}")

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)
    month_name = DANISH_MONTH_NAMES[month]
    html = f"""<div style='font-family:sans-serif; text-align:center'><h3>{month_name} {year}</h3>"""
    html += "<div style='display:grid; grid-template-columns:repeat(7,1fr); gap:4px;'>"
    for d in DANISH_WEEKDAYS: html += f"<div style='background:#f0f0f0;padding:5px;font-weight:bold'>{d}</div>"
    for week in month_days:
        for day in week:
            bg = "#fff" if day != 0 else "#fafafa"
            border = "1px solid #ddd" if day != 0 else "none"
            content = ""
            if day != 0 and day in shifts_map:
                for s in shifts_map[day]:
                    color = "#f8d7da" if "fri" in s.lower() else "#d1e7dd"
                    content += f"<div style='background:{color};font-size:0.7em;margin:1px;padding:2px;border-radius:3px'>{s}</div>"
            html += f"<div style='background:{bg};border:{border};min-height:80px;padding:2px'><div style='color:#888;font-size:0.8em'>{day if day!=0 else ''}</div>{content}</div>"
    html += "</div></div>"
    return html

def push_to_google_calendar(service, events_df, calendar_id):
    batch = service.new_batch_http_request()
    count = 0
    for _, row in events_df.iterrows():
        is_free = "fri" in str(row['Summary']).lower()
        date_obj = row['Date']
        try:
            start_hm = row['Start_Time']
            end_hm = row['End_Time']
            sh, sm = int(start_hm[:2]), int(start_hm[2:])
            eh, em = int(end_hm[:2]), int(end_hm[2:])
            dt_start = datetime.combine(date_obj, time(sh, sm))
            dt_end = datetime.combine(date_obj, time(eh, em))
            if dt_end < dt_start: dt_end += timedelta(days=1)
            event_body = {
                'summary': row['Summary'], 'description': row['Description'],
                'start': {'dateTime': dt_start.isoformat(), 'timeZone': 'Europe/Copenhagen'},
                'end': {'dateTime': dt_end.isoformat(), 'timeZone': 'Europe/Copenhagen'},
                'transparency': 'transparent' if is_free else 'opaque'
            }
        except:
            event_body = {
                'summary': row['Summary'], 'description': row['Description'],
                'start': {'date': date_obj.strftime('%Y-%m-%d')},
                'end': {'date': (date_obj + timedelta(days=1)).strftime('%Y-%m-%d')},
                'transparency': 'transparent' if is_free else 'opaque'
            }
        batch.add(service.events().insert(calendarId=calendar_id, body=event_body))
        count += 1
    batch.execute()
    return count

# --- STREAMLIT UI ---

# st.set_page_config moved to top
st.title("🏥 Vagtplan & Kalender Manager (Cloud)")

# Google Auth
service = handle_oauth()
col_g1, col_g2 = st.columns([1, 4])
with col_g1:
    if not service:
        try:
            token = oauth2.authorize_button(
                name="🔐 Log ind med Google",
                redirect_uri=REDIRECT_URI,
                scope=" ".join(SCOPES),
                key="google_oauth_btn",
                extras_params={"prompt": "consent", "access_type": "offline"}
            )
            if token:
                # Parse nested token if necessary (based on debug output)
                token_data = token.get('token', token)
                
                # Create credentials object
                creds = Credentials(
                    token=token_data['access_token'],
                    refresh_token=token_data.get('refresh_token'),
                    token_uri=TOKEN_URL,
                    client_id=CLIENT_ID,
                    client_secret=CLIENT_SECRET,
                    scopes=SCOPES
                )
                st.session_state.credentials = creds
                st.rerun()
                
        except Exception as e:
            st.query_params.clear()
            st.rerun()
            
    else:
        st.success("Logget ind på Google")
        if st.button("Log ud"):
            if 'credentials' in st.session_state:
                del st.session_state.credentials
            
            st.query_params.clear()
            st.rerun()

# Fil Upload
uploaded_file = st.file_uploader("Upload vagtplan (Drag & Drop)", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    temp_df, m, y = parse_schedule(uploaded_file, uploaded_file.name)
    if not temp_df.empty:
        # Gem via Cloud Storage (Hvis konfigureret)
        uploaded_file.seek(0)
        status, filename = storage_manager.save_file(uploaded_file, m, y)
        if status == "CREATED": st.toast(f"Gemt i Cloud: {filename}", icon="☁️")
        elif status == "UPDATED": st.toast(f"Opdateret i Cloud: {filename}", icon="🔄")
        elif status == "DISABLED": st.info("Cloud storage ikke konfigureret (Filer gemmes ikke permanent).")
        
        st.session_state.current_df = temp_df
    else:
        st.error("Kunne ikke analysere filen.")

# Main Interface
if 'current_df' in st.session_state:
    df_result = st.session_state.current_df
    
    with st.sidebar:
        st.header("Værktøjer")
        doctors = sorted(df_result['Doctor'].unique())
        selected_doctor = st.selectbox("Vælg Læge", doctors)
        st.divider()
        
        if selected_doctor:
            doc_data = df_result[df_result['Doctor'] == selected_doctor]
            st.metric("Vagter", len(doc_data))
            
            ics_data = generate_ics_string(doc_data)
            st.download_button("📥 Download .ics", ics_data, f"{selected_doctor}.ics", "text/calendar", use_container_width=True)
            
            st.divider()
            st.subheader("Google Sync")
            if service:
                try:
                    calendars = []
                    page_token = None
                    while True:
                        cal_list = service.calendarList().list(pageToken=page_token).execute()
                        for entry in cal_list['items']:
                            if entry.get('accessRole') in ['owner', 'writer']:
                                calendars.append((entry['summary'], entry['id']))
                        page_token = cal_list.get('nextPageToken')
                        if not page_token: break
                    
                    cal_opts = {name: cid for name, cid in calendars}
                    sel_cal = st.selectbox("Kalender", list(cal_opts.keys()))
                    if st.button("📤 Synkroniser"):
                        with st.spinner("Sender data..."):
                            cnt = push_to_google_calendar(service, doc_data, cal_opts[sel_cal])
                            st.success(f"Sendt {cnt} vagter!")
                except Exception as e:
                    st.error(f"Fejl ved kalender: {e}")
            else:
                st.info("Log ind for at synkronisere.")

    if selected_doctor:
        doc_data = df_result[df_result['Doctor'] == selected_doctor]
        st.subheader(f"📅 Kalender: {selected_doctor}")
        st.components.v1.html(render_calendar_html(doc_data), height=650, scrolling=True)