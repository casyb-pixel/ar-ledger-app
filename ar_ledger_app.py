import streamlit as st
import pandas as pd
import datetime
import random
import string
import stripe 
import os
import tempfile
import bcrypt  
import altair as alt 
import time
import matplotlib.pyplot as plt
import matplotlib
import io
import requests  # REQUIRED: Make sure 'requests' is in requirements.txt
from PIL import Image
from fpdf import FPDF
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import streamlit.components.v1 as components 

# --- 1. SAFE IMPORTS ---
try:
    from spellchecker import SpellChecker
    SPELLCHECK_AVAILABLE = True
except ImportError:
    SPELLCHECK_AVAILABLE = False

try:
    import extra_streamlit_components as stx
    COOKIE_MANAGER_AVAILABLE = True
except ImportError:
    COOKIE_MANAGER_AVAILABLE = False

# Import Supabase Client
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# Set Matplotlib to non-interactive mode
matplotlib.use('Agg')

# --- 2. CONFIGURATION ---
fav_icon = "favicon.png" if os.path.exists("favicon.png") else None

st.set_page_config(
    page_title="ProgressBill Pro", 
    page_icon=fav_icon, 
    layout="wide", 
    initial_sidebar_state="auto"
)

# --- 3. INITIALIZE COOKIE MANAGER (MUST BE HERE) ---
cookie_manager = None
if COOKIE_MANAGER_AVAILABLE:
    cookie_manager = stx.CookieManager()

# --- 4. REWARDFUL: PYTHON FALLBACK TRACKING ---
if "via" in st.query_params:
    referral_code = st.query_params["via"]
    # 1. Save to session state
    st.session_state.rewardful_id = referral_code
    # 2. Save to persistent cookie
    if COOKIE_MANAGER_AVAILABLE:
        try:
            cookie_manager.set("rewardful.referral", referral_code, expires_at=datetime.datetime.now() + datetime.timedelta(days=365))
        except Exception as e:
            print(f"Cookie set skipped: {e}")

# --- 5. REWARDFUL JS (Visual only, Logic handled by Python) ---
REWARDFUL_API_KEY = "48a8b0" 

components.html(f"""
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-Z6JK5NFPE3"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', 'G-Z6JK5NFPE3');
    </script>

    <script>
    (function(w,r){{w._rwq=r;w[r]=w[r]||function(){{(w[r].q=w[r].q||[]).push(arguments)}};
    w[r].q=w[r].q||[];}})(window,'rewardful');
    rewardful('ready', function() {{ console.log("Rewardful JS Loaded"); }});
    </script>
    <script async src='https://r.wdfl.co/rw.js' data-rewardful='{REWARDFUL_API_KEY}'></script>
""", height=0, width=0)

# --- ADMIN & CONSTANTS ---
ADMIN_USERNAME = "admin" 
BASE_PRICE = 99.00 
AFFILIATE_COMMISSION_PER_USER = 24.75 
STRIPE_PRICE_LOOKUP_KEY = "pro_monthly_99" 
BB_WATERMARK = "ProgressBill Pro | Powered by Balance & Build Consulting"
TERMS_URL = "https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf"

# --- 3. CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #f4f6f9; color: #000000 !important; }
    [data-testid="stSidebar"] { background-color: #2B588D; }
    [data-testid="stSidebar"] * { color: white !important; }
    div.row-widget.stRadio > div { flex-direction: row; }
    .dashboard-card {
        background-color: white; padding: 20px; border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;
        border-left: 5px solid #2B588D; color: black !important;
    }
    .card-title { color: #6c757d; font-size: 14px; font-weight: 600; text-transform: uppercase; margin-bottom: 5px; }
    .card-value { color: #2B588D; font-size: 28px; font-weight: bold; margin: 0; }
    .card-sub { color: #28a745; font-size: 12px; margin-top: 5px; }
    .stButton button {
        width: 100%; height: 80px; border-radius: 12px !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
        background-color: rgba(255,255,255,0.1) !important;
        color: white !important; font-weight: bold; transition: all 0.2s;
        display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px;
    }
    .stButton button:hover { background-color: #DAA520 !important; border-color: #DAA520 !important; transform: translateY(-2px); }
    h1, h2, h3 { color: #2B588D !important; font-family: 'Helvetica', sans-serif; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 4. CONNECTIONS SETUP ---

if "STRIPE_SECRET_KEY" in st.secrets:
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets.get("STRIPE_PUBLISHABLE_KEY", "")
else:
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_fallback")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "pk_test_fallback")

@st.cache_resource
def get_engine():
    try:
        db_url = st.secrets["connections"]["supabase"]["url"]
        return create_engine(db_url, poolclass=NullPool)
    except Exception as e:
        return None

engine = get_engine()

@st.cache_resource
def init_supabase():
    try:
        url = st.secrets.get("SUPABASE_API_URL") or os.environ.get("SUPABASE_API_URL")
        key = st.secrets.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY")
        if url and key and SUPABASE_AVAILABLE:
            return create_client(url, key)
        return None
    except:
        return None

supabase = init_supabase()

# --- DATABASE FUNCTIONS ---
def run_query(query, params=None):
    if not engine: return pd.DataFrame()
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=params)
    except Exception as e:
        return pd.DataFrame() 

def execute_statement(query, params=None):
    if not engine: return
    try:
        with engine.begin() as conn: 
            conn.execute(text(query), params)
    except Exception as e:
        st.error(f"Database Error: {e}")
        raise e

def init_db():
    if not engine: return
    try:
        with engine.begin() as conn:
            conn.execute(text('''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT,
                logo_data BYTEA, terms_conditions TEXT, company_name TEXT, company_address TEXT, 
                company_phone TEXT, subscription_status TEXT DEFAULT 'Inactive', created_at TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT, referral_code TEXT UNIQUE, 
                referral_count INTEGER DEFAULT 0, referred_by TEXT
            )'''))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY, user_id INTEGER, name TEXT, client_name TEXT,
                quoted_price REAL, start_date TEXT, duration INTEGER,
                billing_street TEXT, billing_city TEXT, billing_state TEXT, billing_zip TEXT,
                site_street TEXT, site_city TEXT, site_state TEXT, site_zip TEXT,
                is_tax_exempt INTEGER DEFAULT 0, po_number TEXT, status TEXT DEFAULT 'Bidding', scope_of_work TEXT
            )'''))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY, user_id INTEGER, project_id INTEGER, invoice_num INTEGER, 
                amount REAL, issue_date TEXT, description TEXT, tax REAL DEFAULT 0
            )'''))
            conn.execute(text('''CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY, user_id INTEGER, project_id INTEGER, amount REAL, 
                payment_date TEXT, notes TEXT
            )'''))
    except: pass 

init_db()

# --- 5. HELPER FUNCTIONS ---
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def get_referral_stats(my_code):
    if not my_code: return 0, 0
    df = run_query("SELECT COUNT(*) FROM users WHERE referred_by=:code AND subscription_status IN ('Active', 'Trial')", params={"code": my_code})
    if not df.empty:
        active_count = df.iloc[0, 0]
        discount_percent = min(active_count * 10, 100)
        return active_count, discount_percent
    return 0, 0

# --- NEW: REWARDFUL API LOOKUP (Server-Side Bypass) ---
def get_rewardful_affiliate_id(referral_code):
    """Bypasses browser sandbox by asking Rewardful API directly for the ID."""
    if not referral_code: return None
    
    # Try to get secret key from secrets or env
    secret = None
    if "REWARDFUL_SECRET_KEY" in st.secrets:
        secret = st.secrets["REWARDFUL_SECRET_KEY"]
    else:
        secret = os.environ.get("REWARDFUL_SECRET_KEY")
        
    if not secret:
        print("Warning: REWARDFUL_SECRET_KEY not found.")
        return None

    try:
        # We fetch affiliates and look for a match. 
        # Note: Ideally we filter via API, but basic iteration works for <100 affiliates
        resp = requests.get("https://api.getrewardful.com/v1/affiliates", auth=(secret, ""), params={"limit": 100})
        if resp.status_code == 200:
            data = resp.json().get('data', [])
            for aff in data:
                # Check main token
                if aff.get('token') == referral_code:
                    return aff.get('id')
                # Check specific links
                for link in aff.get('links', []):
                    if link.get('token') == referral_code:
                        return aff.get('id')
    except Exception as e:
        print(f"Rewardful API Error: {e}")
        
    return None

def parse_currency(value):
    if not value: return 0.0
    if isinstance(value, (int, float)): return float(value)
    clean = str(value).replace('$', '').replace(',', '').strip()
    try: return float(clean)
    except: return 0.0

def run_spell_check(text):
    if not SPELLCHECK_AVAILABLE or not text: return None
    spell = SpellChecker()
    construction_words = [
        'hvac', 'pvc', 'abs', 'rebar', 'drywall', 'sheetrock', 'subfloor', 'joist', 'truss', 
        'framing', 'soffit', 'fascia', 'stucco', 'concrete', 'retrofit', 'excavation', 
        'backfill', 'rough-in', 'caulking', 'grout', 'galvanized', 'breaker', 'conduit',
        'fixture', 'demolition', 'reno', 'remodel', 'permit', 'subcontractor'
    ]
    spell.word_frequency.load_words(construction_words)
    words = spell.split_words(text)
    misspelled = spell.unknown(words)
    suggestions = {}
    for word in misspelled:
        corr = spell.correction(word)
        if corr and corr != word: suggestions[word] = corr
    return suggestions

def metric_card(title, value, subtext=""):
    st.markdown(f"""<div class="dashboard-card"><div class="card-title">{title}</div><div class="card-value">{value}</div><div class="card-sub">{subtext}</div></div>""", unsafe_allow_html=True)

def clean_text(text):
    if not text: return ""
    text = str(text)
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00A0': ' '
    }
    for k, v in replacements.items(): text = text.replace(k, v)
    return text.encode('latin-1', 'replace').decode('latin-1')

class BB_PDF(FPDF):
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.set_text_color(180, 180, 180); self.cell(0, 10, BB_WATERMARK, 0, 0, 'C')

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = BB_PDF(); pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=20)
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG"); tmp_path = tmp.name
            pdf.image(tmp_path, 10, 10, 35); os.unlink(tmp_path)
        except: pass
    c_name_txt = clean_text(company_info.get('name', '')); c_addr_txt = clean_text(company_info.get('address', ''))
    pdf.set_xy(120, 15); pdf.set_font("Arial", "B", 12); pdf.cell(0, 5, c_name_txt, ln=1, align='R')
    pdf.set_font("Arial", size=10); pdf.multi_cell(0, 5, c_addr_txt, align='R')
    pdf.set_xy(120, 35); pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, f"INVOICE #{inv_data['number']}", ln=1, align='R')
    pdf.set_font("Arial", "B", 10); pdf.set_text_color(0, 0, 0); pdf.cell(0, 5, f"DATE: {inv_data['date']}", ln=1, align='R')
    if project_info.get('po_number'): pdf.cell(0, 5, f"PO #: {clean_text(project_info['po_number'])}", ln=1, align='R')
    pdf.set_xy(10, 60); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "BILL TO:", ln=1)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, clean_text(project_info['client_name']), ln=1)
    if project_info.get('billing_street'): pdf.cell(0, 5, clean_text(project_info['billing_street']), ln=1); pdf.cell(0, 5, f"{clean_text(project_info['billing_city'])}, {clean_text(project_info['billing_state'])} {clean_text(project_info['billing_zip'])}", ln=1)
    right_x = 110; current_y = 60; pdf.set_xy(right_x, current_y); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "PROJECT SITE:"); current_y += 5; pdf.set_xy(right_x, current_y)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, clean_text(project_info['name']))
    if project_info.get('site_street'): current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, clean_text(project_info['site_street'])); current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, f"{clean_text(project_info['site_city'])}, {clean_text(project_info['site_state'])} {clean_text(project_info['site_zip'])}")
    pdf.set_xy(10, 95); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "DESCRIPTION:", ln=1); pdf.set_font("Arial", size=10); pdf.multi_cell(0, 5, clean_text(inv_data['description']))
    pdf.ln(10); pdf.cell(0, 5, f"Subtotal: ${inv_data['amount'] - inv_data['tax']:,.2f}", ln=1, align='R'); pdf.cell(0, 5, f"Tax: ${inv_data['tax']:,.2f}", ln=1, align='R'); pdf.set_font("Arial", "B", 12); pdf.cell(0, 10, f"TOTAL: ${inv_data['amount']:,.2f}", border="T", ln=1, align='R')
    if terms: pdf.ln(15); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "TERMS & CONDITIONS:", ln=1); pdf.set_font("Arial", size=8); pdf.multi_cell(0, 4, clean_text(terms))
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_statement_pdf(ledger_df, logo_data, company_info, project_name, client_name):
    pdf = BB_PDF(); pdf.add_page()
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG"); tmp_path = tmp.name
            pdf.image(tmp_path, 10, 10, 35); os.unlink(tmp_path)
        except: pass
    pdf.set_xy(120, 15); pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141); pdf.cell(0, 10, "PROJECT STATEMENT", ln=1, align='R')
    pdf.set_font("Arial", size=10); pdf.set_text_color(0, 0, 0); pdf.cell(0, 5, f"Date: {datetime.date.today()}", ln=1, align='R'); pdf.ln(10)
    pdf.set_font("Arial", "B", 12); pdf.cell(0, 5, f"Project: {clean_text(project_name)}", ln=1); pdf.set_font("Arial", size=10); pdf.cell(0, 5, f"Client: {clean_text(client_name)}", ln=1); pdf.ln(10)
    pdf.set_fill_color(43, 88, 141); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 8, "Date", 1, 0, 'C', 1); pdf.cell(80, 8, "Description", 1, 0, 'L', 1); pdf.cell(25, 8, "Charge", 1, 0, 'R', 1); pdf.cell(25, 8, "Payment", 1, 0, 'R', 1); pdf.cell(30, 8, "Balance", 1, 1, 'R', 1)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=9); fill = False
    for index, row in ledger_df.iterrows():
        if fill: pdf.set_fill_color(240, 240, 240)
        else: pdf.set_fill_color(255, 255, 255)
        pdf.cell(30, 8, str(row['Date']), 1, 0, 'C', fill); pdf.cell(80, 8, clean_text(str(row['Details'])[:40]), 1, 0, 'L', fill); pdf.cell(25, 8, f"${row['Charge']:,.2f}", 1, 0, 'R', fill); pdf.cell(25, 8, f"${row['Payment']:,.2f}", 1, 0, 'R', fill); pdf.cell(30, 8, f"${row['Balance']:,.2f}", 1, 1, 'R', fill); fill = not fill
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_dashboard_pdf(metrics, company_name, logo_data, chart_data):
    pdf = BB_PDF(); pdf.add_page(); pdf.set_fill_color(43, 88, 141); pdf.rect(0, 0, 210, 40, 'F')
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG"); tmp_path = tmp.name
            pdf.image(tmp_path, 10, 8, 25); os.unlink(tmp_path)
        except: pass
    pdf.set_xy(40, 10); pdf.set_font("Arial", "B", 20); pdf.set_text_color(255, 255, 255); pdf.cell(0, 10, "EXECUTIVE FINANCIAL REPORT", ln=1); pdf.set_xy(40, 20); pdf.set_font("Arial", size=12); pdf.cell(0, 10, f"{clean_text(company_name)} | Date: {datetime.date.today()}", ln=1); pdf.ln(20)
    pdf.set_text_color(43, 88, 141); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, "Key Performance Indicators", ln=1); pdf.ln(2)
    pdf.set_fill_color(218, 165, 32); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 11)
    pdf.cell(100, 10, "Metric Category", 1, 0, 'L', 1); pdf.cell(60, 10, "Value", 1, 1, 'R', 1); pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=11); fill = False
    for key, value in metrics.items():
        if fill: pdf.set_fill_color(245, 245, 245)
        else: pdf.set_fill_color(255, 255, 255)
        pdf.cell(100, 10, key, 1, 0, 'L', fill); pdf.cell(60, 10, value, 1, 1, 'R', fill); fill = not fill
    pdf.ln(15); pdf.set_text_color(43, 88, 141); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, "Visual Analysis", ln=1)
    if chart_data:
        total_rev = chart_data['Invoiced'] + chart_data['Collected'] + chart_data['Outstanding']
        if total_rev > 0:
            plt.figure(figsize=(6, 4)); categories = ['Invoiced', 'Collected', 'Outstanding AR']; values = [chart_data['Invoiced'], chart_data['Collected'], chart_data['Outstanding']]; colors = ['#2B588D', '#28a745', '#DAA520']; plt.bar(categories, values, color=colors); plt.title('Revenue Distribution', color='#2B588D'); plt.grid(axis='y', linestyle='--', alpha=0.7)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_chart1:
                plt.savefig(tmp_chart1.name, format='png', bbox_inches='tight'); pdf.image(tmp_chart1.name, x=10, y=pdf.get_y() + 5, w=90); os.unlink(tmp_chart1.name)
        else: pdf.set_font("Arial", "I", 10); pdf.text(x=20, y=pdf.get_y() + 20, txt="No financial activity recorded yet.")
        pie_sizes = [chart_data['Invoiced'], chart_data['Remaining']]
        if sum(pie_sizes) > 0:
            plt.clf(); plt.figure(figsize=(6, 4)); labels = ['Invoiced', 'Remaining']; plt.pie(pie_sizes, labels=labels, autopct='%1.1f%%', colors=['#2B588D', '#eef2f5'], startangle=90); plt.title('Contract Progress', color='#2B588D')
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_chart2:
                plt.savefig(tmp_chart2.name, format='png', bbox_inches='tight'); pdf.image(tmp_chart2.name, x=110, y=pdf.get_y() + 5, w=90); os.unlink(tmp_chart2.name)
        else: pdf.set_font("Arial", "I", 10); pdf.text(x=130, y=pdf.get_y() + 20, txt="No contracts active.")
    return pdf.output(dest='S').encode('latin-1', 'replace')

def create_checkout_session(customer_id, discount_percent, referral_id=None):
    try:
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        if not prices.data: return None, "Price Not Found in Stripe"
        
        session_args = {
            'customer': customer_id,
            'payment_method_types': ['card'],
            'line_items': [{'price': prices.data[0].id, 'quantity': 1}],
            'mode': 'subscription',
            'success_url': 'https://progressbillpro.com',
            'cancel_url': 'https://progressbillpro.com'
        }
        
        # --- REWARDFUL API BYPASS ---
        # If we have a referral code (e.g. 'test-referral'), we need to exchange it 
        # for an Affiliate ID via the API because the JS sandbox blocked the cookie conversion.
        if referral_id:
            # 1. Try to see if it's already an ID (unlikely if cookie failed)
            session_args['client_reference_id'] = referral_id
            
            # 2. Try to look it up via API
            aff_id = get_rewardful_affiliate_id(referral_id)
            if aff_id:
                # If we found an ID, use it. This attributes the sale to the affiliate.
                session_args['client_reference_id'] = aff_id
            
        session = stripe.checkout.Session.create(**session_args)
        return session.url, None
    except Exception as e: return None, str(e)

def create_stripe_customer(email, name):
    try: return stripe.Customer.create(email=email, name=name).id
    except: return None

# --- 6. APP LOGIC & NAVIGATION ---
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'username' not in st.session_state: st.session_state.username = ""
if 'page' not in st.session_state: st.session_state.page = "Dashboard"

# --- AUTO-LOGIN VIA COOKIES ---
if st.session_state.user_id is None and COOKIE_MANAGER_AVAILABLE and not st.session_state.get("manual_logout", False):
    time.sleep(0.1)
    cookies = cookie_manager.get_all()
    user_cookie = cookies.get("progressbill_user")
    
    if user_cookie:
        df_cookie = run_query("SELECT id, username, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE username=:u", params={"u": user_cookie})
        if not df_cookie.empty:
            rec = df_cookie.iloc[0]
            st.session_state.user_id = int(rec['id'])
            st.session_state.username = rec['username']
            st.session_state.sub_status = rec['subscription_status']
            st.session_state.stripe_cid = rec['stripe_customer_id']
            st.session_state.created_at = rec['created_at']
            st.session_state.my_ref_code = rec['referral_code']
            st.rerun()

# --- LOGIN / SIGNUP SCREENS ---
if st.session_state.user_id is None:
    if os.path.exists("BB_logo.png"):
        st.image("BB_logo.png", width=200)
    else:
        st.title("ProgressBill Pro")
        st.caption("Powered by Balance & Build Consulting")

    tab1, tab2 = st.tabs(["Login", "Signup (Start Free Trial)"])

    # --- TAB 1: LOGIN (Password + OTP) ---
    with tab1:
        login_mode = st.radio("Login Method:", ["Password", "Forgot Password / Login with Code"], label_visibility="collapsed")

        if login_mode == "Password":
            with st.form("login_form"):
                u = st.text_input("Username").lower().strip()
                p = st.text_input("Password", type="password")
                remember = st.checkbox("Remember Me (Keep me logged in)")
                submitted = st.form_submit_button("Login")

                if submitted:
                    df = run_query("SELECT id, password, email, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE username=:u", params={"u": u})
                    
                    if not df.empty:
                        rec = df.iloc[0]
                        if check_password(p, rec['password']):
                            st.session_state.user_id = int(rec['id'])
                            st.session_state.username = u
                            st.session_state.email = rec['email']
                            st.session_state.sub_status = rec['subscription_status']
                            st.session_state.stripe_cid = rec['stripe_customer_id']
                            st.session_state.created_at = rec['created_at']
                            st.session_state.my_ref_code = rec['referral_code']
                            
                            if remember and COOKIE_MANAGER_AVAILABLE:
                                cookie_manager.set("progressbill_user", u, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                            
                            st.success("Login successful!")
                            st.rerun()
                        else:
                            st.error("Incorrect password")
                    else:
                        st.error("Username not found")

        else: # OTP / Magic Code Login
            if not supabase:
                st.error("Email service not configured. Please contact support.")
            else:
                st.info("Enter your email. We will send a 6-digit code to log you in.")
                email_otp = st.text_input("Email Address", key="otp_email")
                
                col_a, col_b = st.columns(2)
                
                # Button 1: Send Code
                if col_a.button("Send Code"):
                    if email_otp:
                        try:
                            supabase.auth.sign_in_with_otp({"email": email_otp})
                            st.success("Code sent! Check your email.")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("Please enter an email.")

                # Button 2: Verify & Connect to DB
                otp_token = st.text_input("Enter 6-digit Code", key="otp_code")
                if col_b.button("Verify & Login"):
                    if email_otp and otp_token:
                        try:
                            res = supabase.auth.verify_otp({"email": email_otp, "token": otp_token, "type": "email"})
                            
                            # Bridge to SQL Database
                            df = run_query("SELECT id, username, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE email=:e", params={"e": email_otp})
                            
                            if not df.empty:
                                rec = df.iloc[0]
                                st.session_state.user_id = int(rec['id'])
                                st.session_state.username = rec['username']
                                st.session_state.email = email_otp
                                st.session_state.sub_status = rec['subscription_status']
                                st.session_state.stripe_cid = rec['stripe_customer_id']
                                st.session_state.created_at = rec['created_at']
                                st.session_state.my_ref_code = rec['referral_code']
                                
                                st.success("Verified! Logging you in...")
                                st.rerun()
                            else:
                                st.error("Login verified, but we couldn't find your account details in the database.")
                        except Exception as e:
                            st.error(f"Invalid Code or Error: {e}")

    # --- TAB 2: SIGNUP ---
    with tab2:
        st.header("Create New Account")
        st.caption("Start your 30-Day Free Trial")
        with st.form("signup"):
            u = st.text_input("Username").lower().strip()
            p = st.text_input("Password", type="password")
            e = st.text_input("Email")
            
            # Auto-fill from Python capture
            default_ref = st.session_state.get("rewardful_id", "")
            ref_input = st.text_input("Referral/Affiliate Code (Optional)", value=default_ref)
            
            st.markdown("---")
            st.markdown(f"Please read the [Terms and Conditions]({TERMS_URL}) before signing up.")
            terms_agreed = st.checkbox("I acknowledge that I have read and agree to the Terms and Conditions.", value=False)
            
            submitted_sign = st.form_submit_button("Create Account")
            
            if submitted_sign:
                if not terms_agreed:
                    st.error("You must agree to the Terms and Conditions.")
                elif u and p and e:
                    try:
                        check = run_query("SELECT id FROM users WHERE username=:u", params={"u": u})
                        if not check.empty:
                            st.error("Username already taken.")
                        else:
                            # 1. Register in Supabase Auth
                            if supabase:
                                try:
                                    supabase.auth.sign_up({"email": e, "password": p})
                                except Exception as auth_err:
                                    print(f"Auth warning: {auth_err}")

                            # 2. Register in SQL Database
                            h_p = hash_password(p)
                            cid = create_stripe_customer(e, u)
                            my_ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                            today_str = str(datetime.date.today())
                            
                            if ref_input:
                                execute_statement("UPDATE users SET referral_count = referral_count + 1 WHERE referral_code=:c", params={"c": ref_input})
                            
                            execute_statement(
                                "INSERT INTO users (username, password, email, stripe_customer_id, referral_code, created_at, subscription_status, referred_by) VALUES (:u, :p, :e, :cid, :rc, :ca, 'Trial', :rb)",
                                params={"u": u, "p": h_p, "e": e, "cid": cid, "rc": my_ref_code, "ca": today_str, "rb": ref_input}
                            )
                            st.success("Account Created! Please switch to Login tab.")
                    except Exception as err:
                        st.error(f"Error: {err}")
                else:
                    st.warning("Please fill all fields")

else:
    # --- LOGGED IN USER CONTEXT ---
    user_id = st.session_state.user_id
    curr_username = st.session_state.username
    
    # Reload Context
    # FIX: Added 'terms_conditions' to prevent Invoice Crash
    df_user = run_query("SELECT subscription_status, created_at, referral_code, referred_by, company_name, company_address, logo_data, terms_conditions FROM users WHERE id=:id", params={"id": user_id})
    if df_user.empty:
        st.session_state.clear()
        st.rerun()
    
    row = df_user.iloc[0]
    status, created_at_str, my_code, referred_by = row['subscription_status'], row['created_at'], row['referral_code'], row['referred_by']
    c_name, c_addr, logo, terms = row['company_name'], row['company_address'], row['logo_data'], row['terms_conditions']
    
    # --- PRICING & SUBSCRIPTION LOGIC ---
    active_referrals, discount_percent_earned = get_referral_stats(my_code)
    discount_from_affiliate = 10 if referred_by else 0
    total_discount = min(discount_percent_earned + discount_from_affiliate, 100)
    
    final_price = BASE_PRICE * (1 - (total_discount / 100))

    # Check Trial
    days_left = 0
    trial_active = False
    if status == 'Trial' and created_at_str:
        try:
            start_date = datetime.datetime.strptime(created_at_str, '%Y-%m-%d').date()
            days_left = 30 - (datetime.date.today() - start_date).days
            if days_left > 0:
                trial_active = True
        except:
            pass
    
    # --- AFFILIATE VIEW ---
    if status == 'Affiliate':
        st.warning("⚠️ This is an Affiliate Account. Access restricted to API tracking only.")
        if st.button("Logout"): 
            if COOKIE_MANAGER_AVAILABLE: 
                cookie_manager.delete("progressbill_user")
            st.session_state.clear()
            st.session_state['manual_logout'] = True
            st.rerun()
        st.stop()

    # --- SUBSCRIPTION ENFORCEMENT ---
    if status != 'Active' and not trial_active and curr_username != ADMIN_USERNAME:
        st.markdown("## 🔒 Subscription Required")
        st.error("Your Free Trial has expired.")
        
        st.divider()
        st.subheader("Plan Details")
        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("Base Price", f"${BASE_PRICE:.2f}/mo")
        col_p2.metric("Your Discount", f"{total_discount}%", help=f"{active_referrals} Active Referrals + Signup Bonus")
        col_p3.metric("Your Final Price", f"${final_price:.2f}/mo")
        
        st.caption(f"Pricing is dynamic! Refer more users to lower your bill. You have {active_referrals} active referrals.")
        st.divider()

        if total_discount >= 100:
            st.balloons()
            st.success("🎉 You have earned FREE ACCESS via Referrals!")
            if st.button("Activate Free Lifetime Access"):
                execute_statement("UPDATE users SET subscription_status='Active' WHERE id=:id", params={"id": user_id})
                st.session_state.sub_status = 'Active'
                st.rerun()
        else:
            if st.session_state.stripe_cid:
                # 1. PRIMARY: Get ID from the Database (Permanent)
                rewardful_id = referred_by
                
                # 2. FALLBACK: Check Session/Cookies
                if not rewardful_id:
                    rewardful_id = st.session_state.get("rewardful_id")
                    if not rewardful_id and COOKIE_MANAGER_AVAILABLE:
                        cookies = cookie_manager.get_all()
                        rewardful_id = cookies.get("rewardful.referral")
                
                # 3. Create the session
                url, err = create_checkout_session(st.session_state.stripe_cid, total_discount, referral_id=rewardful_id)
                
                if url:
                    st.link_button(f"👉 Subscribe for ${final_price:.2f}/mo", url, type="primary")
                else:
                    st.error("Error connecting to Stripe.")
            
        st.markdown("---")
        if st.button("Logout"):
            if COOKIE_MANAGER_AVAILABLE:
                cookie_manager.delete("progressbill_user")
            st.session_state.clear()
            st.session_state['manual_logout'] = True
            st.rerun()
        st.stop()
    
    # --- SIDEBAR MENU ---
    with st.sidebar:
        if logo: 
             try:
                st.image(Image.open(io.BytesIO(logo)), width=120)
             except: st.header(c_name or "Menu")
        else: st.header("Menu")
        col1, col2 = st.columns(2)
        with col1:
            if curr_username == ADMIN_USERNAME:
                if st.button("👥\nAdmin", use_container_width=True): st.session_state.page = "Admin Dashboard"
            else:
                if st.button("📊\nDash", use_container_width=True): st.session_state.page = "Dashboard"
                if st.button("📝\nInvoice", use_container_width=True): st.session_state.page = "Invoices"
                if st.button("⚙️\nSettings", use_container_width=True): st.session_state.page = "Settings"
        with col2:
            if curr_username == ADMIN_USERNAME:
                 if st.button("🚪\nLogout", use_container_width=True):
                    if COOKIE_MANAGER_AVAILABLE:
                        cookie_manager.delete("progressbill_user")
                    st.session_state.clear()
                    st.session_state['manual_logout'] = True
                    st.rerun()
            else:
                if st.button("📁\nProjs", use_container_width=True): st.session_state.page = "Projects"
                if st.button("💰\nPay", use_container_width=True): st.session_state.page = "Payments"
                if st.button("🚪\nLogout", use_container_width=True):
                    if COOKIE_MANAGER_AVAILABLE:
                        cookie_manager.delete("progressbill_user")
                    st.session_state.clear()
                    st.session_state['manual_logout'] = True
                    st.rerun()
        
        st.divider()
        with st.expander("📱 Install App on Mobile"):
            st.write("To add this app to your home screen:")
            st.markdown("""
            **iPhone (Safari):**
            1. Tap the **Share** button.
            2. Tap **'Add to Home Screen'**.
    
            **Android (Chrome):**
            1. Tap the **three dots**.
            2. Tap **'Install App'**.
            """)   
        
        # Change Password Feature
        st.divider()
        with st.expander("🔒 Change Password"):
