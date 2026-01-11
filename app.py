import streamlit as st
import pandas as pd
import re
import uuid
import calendar
import os
from datetime import datetime, timedelta, time

# --- KONFIGURATION & KONSTANTER ---
MONTH_MAP = {
    'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6,
    'juli': 7, 'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}

DANISH_MONTH_NAMES = [
    "", "Januar", "Februar", "Marts", "April", "Maj", "Juni", 
    "Juli", "August", "September", "Oktober", "November", "December"
]

DANISH_WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]

# --- KONFIGURATIONS MANAGER ---
class ConfigManager:
    def __init__(self):
        self.durations = {}
        self.details = {}
        self.default_duration = {'start': '0800', 'end': '1600'} # Standard
        
        # Indlæs filer hvis de findes
        self.load_durations('shift-durations.csv')
        self.load_details('shift-details.csv')

    def load_durations(self, filepath):
        if not os.path.exists(filepath): return
        try:
            # Forventet format: Assignment;Start;end
            df = pd.read_csv(filepath, sep=';', keep_default_na=False)
            for _, row in df.iterrows():
                key = str(row[0]).strip().lower()
                self.durations[key] = {
                    'start': str(row[1]).strip().zfill(4),
                    'end': str(row[2]).strip().zfill(4)
                }
            
            if '*default*' in self.durations:
                self.default_duration = self.durations['*default*']
        except Exception as e:
            print(f"Fejl ved indlæsning af varigheder: {e}")

    def load_details(self, filepath):
        if not os.path.exists(filepath): return
        try:
            # Forventet format: ;mandag;tirsdag... (Header)
            df = pd.read_csv(filepath, sep=';', keep_default_na=False)
            
            # Kortlæg kolonner til ugedage
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
                
                found_days = 0
                for i in range(1, len(row)):
                    if found_days < len(day_map):
                        day_idx = day_map[found_days]
                        val = str(row[i]).strip()
                        if val:
                            self.details[key][day_idx] = val
                        found_days += 1
                        
        except Exception as e:
            print(f"Fejl ved indlæsning af detaljer: {e}")

    def get_time_rules(self, shift_name):
        """Finder bedste match for tidsregler."""
        s_name = shift_name.lower()
        if s_name in self.durations: return self.durations[s_name]
        
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
        """Tjekker om der er en specifik label for ugedagen."""
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

# Initialiser Config
config = ConfigManager()

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
    # 1. Indlæs Data
    if 'xls' in file_type:
        df = pd.read_excel(file_obj, header=None)
    else:
        string_data = file_obj.getvalue().decode("utf-8", errors='ignore')
        sep = ';' if ';' in string_data.splitlines()[0] else ','
        file_obj.seek(0)
        df = pd.read_csv(file_obj, sep=sep, header=None, keep_default_na=False)

    month, year = find_month_year(df)
    
    # 2. Find Dato-rækken
    date_row_idx = -1
    for idx, row in df.iterrows():
        numerics = [x for x in row if str(x).strip().isdigit() and 1 <= int(x) <= 31]
        if len(numerics) > 5:
            date_row_idx = idx
            break
            
    if date_row_idx == -1: return pd.DataFrame()

    # 3. Kortlæg kolonner
    col_to_date = {} 
    row_vals = df.iloc[date_row_idx]
    curr_month, curr_year = month, year
    last_day = 0
    
    for c_idx in range(len(df.columns)):
        val = str(row_vals[c_idx]).strip()
        if val.isdigit():
            day = int(val)
            if day < last_day: 
                curr_month += 1
                if curr_month > 12: curr_month, curr_year = 1, curr_year + 1
            last_day = day
            try:
                col_to_date[c_idx] = datetime(curr_year, curr_month, day).date()
            except: continue

    if not col_to_date: return pd.DataFrame()
    first_date_col = min(col_to_date.keys())
    
    base_header_cols = list(range(0, first_date_col))
    if base_header_cols:
        df[base_header_cols[0]] = df[base_header_cols[0]].replace('', pd.NA).ffill()

    events = []
    
    # 4. Udpak Vagter
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
                # Opdater label hvis der var tekst i mellemrummene
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
                        
                        # Anvend mapping fra konfigurationsfiler
                        final_summary = active_label
                        detail_label = config.get_detail_label(active_label, date_obj)
                        if detail_label:
                            final_summary = detail_label + " AMB"
                        
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

    return pd.DataFrame(events)

def generate_ics_string(events_df):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HospitalsVagtplan//DA", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    
    for _, row in events_df.iterrows():
        uid = str(uuid.uuid4())
        dtstamp = datetime.now().strftime('%Y%m%dT%H%M%SZ')
        
        date_obj = row['Date']
        start_hm = row['Start_Time']
        end_hm = row['End_Time']
        
        try:
            sh = int(start_hm[:2])
            sm = int(start_hm[2:])
            eh = int(end_hm[:2])
            em = int(end_hm[2:])
            
            dt_start = datetime.combine(date_obj, time(sh, sm))
            dt_end = datetime.combine(date_obj, time(eh, em))
            
            if dt_end < dt_start:
                dt_end += timedelta(days=1)
                
            start_str = dt_start.strftime('%Y%m%dT%H%M%S')
            end_str = dt_end.strftime('%Y%m%dT%H%M%S')
            time_block = f"DTSTART:{start_str}\nDTEND:{end_str}"
            
        except ValueError:
            d_str = date_obj.strftime('%Y%m%d')
            time_block = f"DTSTART;VALUE=DATE:{d_str}"

        # Status: Fri = Transparent, Arbejde = Opaque
        status = "TRANSP:TRANSPARENT" if "fri" in str(row['Summary']).lower() else "TRANSP:OPAQUE"
        
        lines.extend([
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{dtstamp}",
            time_block,
            f"SUMMARY:{row['Summary']}",
            f"DESCRIPTION:{row['Description']}", status, "END:VEVENT"
        ])
    lines.append("END:VCALENDAR")
    return "\n".join(lines)

# --- VISUALISERING ---

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
    
    # Dansk Måned
    month_name = DANISH_MONTH_NAMES[month]
    
    html = f"""
    <style>
        .cal-container {{ font-family: sans-serif; max-width: 100%; }}
        .cal-header {{ text-align: center; font-size: 1.5em; margin-bottom: 15px; font-weight: bold; color: #333; }}
        .cal-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 5px; }}
        .cal-day-header {{ text-align: center; font-weight: bold; background: #f0f2f6; padding: 8px; border-radius: 4px; }}
        .cal-cell {{ min-height: 100px; padding: 5px; border: 1px solid #e0e0e0; border-radius: 4px; background: white; position: relative; }}
        .cal-cell.empty {{ background: #fafafa; border: none; }}
        .day-num {{ font-weight: bold; color: #555; margin-bottom: 5px; }}
        .shift-badge {{ background-color: #d1e7dd; color: #0f5132; padding: 2px 5px; border-radius: 3px; margin-bottom: 2px; font-size: 0.75em; display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; cursor: help; }}
        .shift-badge.fri {{ background-color: #f8d7da; color: #842029; }}
    </style>
    <div class="cal-container">
        <div class="cal-header">{month_name} {year}</div>
        <div class="cal-grid">
    """
    
    # Danske ugedage headers
    for day_name in DANISH_WEEKDAYS:
        html += f'<div class="cal-day-header">{day_name}</div>'

    for week in month_days:
        for day in week:
            if day == 0:
                html += '<div class="cal-cell empty"></div>'
            else:
                content = ""
                if day in shifts_map:
                    for shift in shifts_map[day]:
                        css = "fri" if "fri" in shift.lower() else "work"
                        short_name = (shift[:25] + '..') if len(shift) > 25 else shift
                        content += f'<span class="shift-badge {css}" title="{shift}">{short_name}</span>'
                
                html += f'<div class="cal-cell"><div class="day-num">{day}</div>{content}</div>'
    
    html += "</div></div>"
    return html

# --- STREAMLIT UI (DANSK) ---

st.set_page_config(page_title="Vagtplan Konvertering", layout="wide")

st.title("🏥 Vagtplan Konvertering")
st.markdown("Upload en månedlig vagtplan (Excel/CSV) for at generere .ics kalenderfiler.")

# Config Feedback
col1, col2 = st.columns(2)
with col1:
    if config.durations: st.caption(f"✅ Indlæste {len(config.durations)} tidsregler.")
    else: st.caption("⚠️ 'shift-durations.csv' ikke fundet. Bruger standard (08-16).")
with col2:
    if config.details: st.caption(f"✅ Indlæste {len(config.details)} detalje-labels.")
    else: st.caption("⚠️ 'shift-details.csv' ikke fundet.")

# File Uploader (Supports Drag & Drop natively on the whole page)
uploaded_file = st.file_uploader("Upload Vagtplan", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    with st.spinner('Behandler vagtplan...'):
        try:
            df_result = parse_schedule(uploaded_file, uploaded_file.name)
            
            if not df_result.empty:
                st.success(f"Analyse færdig: Fandt {len(df_result)} tildelte vagter.")
                
                with st.sidebar:
                    st.header("Indstillinger")
                    doctors = sorted(df_result['Doctor'].unique())
                    selected_doctor = st.selectbox("Vælg Læge / Initialer", doctors)
                    
                    st.divider()
                    
                    if selected_doctor:
                        doc_data = df_result[df_result['Doctor'] == selected_doctor]
                        st.metric("Antal Vagter", len(doc_data))
                        
                        ics_data = generate_ics_string(doc_data)
                        st.download_button(
                            label="📥 Download .ics Kalender",
                            data=ics_data,
                            file_name=f"Vagtplan_{selected_doctor}.ics",
                            mime="text/calendar",
                            use_container_width=True
                        )

                if selected_doctor:
                    doc_data = df_result[df_result['Doctor'] == selected_doctor]
                    st.subheader(f"📅 Kalender: {selected_doctor}")
                    
                    # Kalender visning (HTML)
                    st.components.v1.html(render_calendar_html(doc_data), height=650, scrolling=True)
            else:
                st.warning("Ingen data fundet. Tjek at filen indeholder en række med datoer (f.eks. 1, 2, 3...).")
                
        except Exception as e:
            st.error(f"Der opstod en fejl: {e}")