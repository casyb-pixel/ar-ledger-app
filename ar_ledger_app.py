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

# --- 3. INITIALIZE COOKIE MANAGER ---
cookie_manager = None
if COOKIE_MANAGER_AVAILABLE:
    cookie_manager = stx.CookieManager()

# --- 4. REWARDFUL: PYTHON FALLBACK TRACKING ---
# This serves as a backup to the Bluehost redirect.
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

# --- 5. REWARDFUL JS (Visual & Backup) ---
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
    rewardful('ready', function() {{ console.log("Rewardful JS Ready"); }});
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
        
        if referral_id:
            session_args['client_reference_id'] = referral_id
            
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
    # FIX: Explicitly selecting 'terms_conditions' to prevent NameError later
    df_user = run_query("SELECT subscription_status, created_at, referral_code, referred_by, company_name, company_address, logo_data, terms_conditions FROM users WHERE id=:id", params={"id": user_id})
    if df_user.empty:
        st.session_state.clear()
        st.rerun()
    
    row = df_user.iloc[0]
    status, created_at_str, my_code, referred_by = row['subscription_status'], row['created_at'], row['referral_code'], row['referred_by']
    
    # FIX: Map 'terms_conditions' from DB to the variable 'terms'
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
        # FIX: Corrected indentation for the Expander block
        with st.expander("🔒 Change Password"):
            new_pass = st.text_input("New Password", type="password")
            if st.button("Update Password"):
                if supabase:
                    try:
                        supabase.auth.update_user({"password": new_pass})
                        st.success("Password updated!")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                else:
                    st.error("Auth service not available.")

        st.markdown("---"); st.caption(f"Ver: 1.0 | User: {curr_username}")

    page = st.session_state.page
    
    # --- ADMIN DASHBOARD ---
    if curr_username == ADMIN_USERNAME and page == "Admin Dashboard":
        st.title("📊 Admin & Affiliate Intelligence")
        tab_refs, tab_activity, tab_alerts, tab_manage = st.tabs(["📈 Referral Stats", "🔥 User Activity", "⚠️ Alerts", "⚙️ Manage Codes"])
        
        with tab_refs:
            st.subheader("Referral Performance Overview")
            def calculate_periods(code):
                now = datetime.datetime.now()
                refs = run_query("SELECT created_at FROM users WHERE referred_by=:c", {"c": code})
                if refs.empty: return 0, 0, 0
                refs['created_at'] = pd.to_datetime(refs['created_at'], errors='coerce')
                d30 = refs[refs['created_at'] >= (now - datetime.timedelta(days=30))].shape[0]
                d60 = refs[refs['created_at'] >= (now - datetime.timedelta(days=60))].shape[0]
                return d30, d60, refs.shape[0]

            st.markdown("#### 🏢 Affiliate Partners")
            affiliates = run_query("SELECT username, referral_code FROM users WHERE subscription_status='Affiliate'")
            if not affiliates.empty:
                aff_data = []
                for _, row in affiliates.iterrows():
                    d30, d60, life = calculate_periods(row['referral_code'])
                    aff_data.append({"Partner": row['username'], "Code": row['referral_code'], "30 Days": d30, "60 Days": d60, "Lifetime": life, "Commission Due": f"${life * AFFILIATE_COMMISSION_PER_USER:,.2f}"})
                st.dataframe(pd.DataFrame(aff_data), use_container_width=True)
            else: st.info("No affiliates found.")

            st.markdown("---")
            st.markdown("#### 👤 Standard Users (Referral Program)")
            referrers = run_query("SELECT DISTINCT referred_by FROM users WHERE referred_by IS NOT NULL AND referred_by != ''")
            if not referrers.empty:
                user_ref_data = []
                aff_codes = affiliates['referral_code'].tolist() if not affiliates.empty else []
                for code in referrers['referred_by'].unique():
                    if code in aff_codes: continue
                    owner = run_query("SELECT username FROM users WHERE referral_code=:c", {"c": code})
                    owner_name = owner.iloc[0,0] if not owner.empty else "Unknown"
                    d30, d60, life = calculate_periods(code)
                    user_ref_data.append({"User": owner_name, "Code": code, "30 Days": d30, "Lifetime": life})
                if user_ref_data: st.dataframe(pd.DataFrame(user_ref_data), use_container_width=True)
                else: st.info("No user-to-user referrals yet.")
            else: st.info("No referrals found.")

        with tab_activity:
            st.subheader("🔥 Most Active Users (Engagement)")
            def get_activity_counts(days):
                cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
                sql_proj = "SELECT user_id, COUNT(*) as cnt FROM projects WHERE start_date >= :d GROUP BY user_id"
                sql_inv = "SELECT user_id, COUNT(*) as cnt FROM invoices WHERE issue_date >= :d GROUP BY user_id"
                sql_pay = "SELECT user_id, COUNT(*) as cnt FROM payments WHERE payment_date >= :d GROUP BY user_id"
                df_p = run_query(sql_proj, {"d": cutoff}); df_i = run_query(sql_inv, {"d": cutoff}); df_pay = run_query(sql_pay, {"d": cutoff})
                activity = {}
                for df, label in [(df_p, 'Projects'), (df_i, 'Invoices'), (df_pay, 'Payments')]:
                    if not df.empty:
                        for _, r in df.iterrows():
                            uid = r['user_id']
                            if uid not in activity: activity[uid] = {'Projects':0, 'Invoices':0, 'Payments':0}
                            activity[uid][label] = r['cnt']
                final_rows = []
                for uid, counts in activity.items():
                    u_res = run_query("SELECT username FROM users WHERE id=:id", {"id": uid})
                    if not u_res.empty:
                        u_name = u_res.iloc[0,0]
                        final_rows.append({"User": u_name, **counts, "Total Actions": sum(counts.values())})
                return pd.DataFrame(final_rows).sort_values("Total Actions", ascending=False) if final_rows else pd.DataFrame()

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("##### Past 7 Days")
                df_7 = get_activity_counts(7)
                if not df_7.empty: st.dataframe(df_7, use_container_width=True)
                else: st.info("No activity in last 7 days.")
            with c2:
                st.markdown("##### Past 30 Days")
                df_30 = get_activity_counts(30)
                if not df_30.empty: st.dataframe(df_30, use_container_width=True)
                else: st.info("No activity in last 30 days.")

        with tab_alerts:
            st.subheader("⚠️ At-Risk / Incomplete Setup")
            risk_users = run_query("SELECT u.username, u.company_name, u.email, COUNT(i.id) as inv_count FROM users u JOIN invoices i ON u.id = i.user_id WHERE (u.company_name IS NULL OR u.company_name = '' OR u.logo_data IS NULL) GROUP BY u.id")
            if not risk_users.empty:
                for _, row in risk_users.iterrows():
                    st.warning(f"**{row['username']}** ({row['email']})")
                    st.write(f"- Has created **{row['inv_count']} invoices** but missing Company Info/Logo.")
            else: st.success("✅ All active users have completed their profiles!")

        with tab_manage:
            st.subheader("Create New Affiliate")
            with st.form("new_affiliate_admin"):
                aff_name = st.text_input("Affiliate Name (Internal ID)")
                aff_code = st.text_input("Custom Referral Code (e.g., INFLUENCER20)")
                submitted_aff = st.form_submit_button("Generate Code")
                if submitted_aff:
                    aff_name_clean = aff_name.lower().strip()
                    fake_email = f"{aff_name_clean.replace(' ', '')}@affiliate.com"
                    fake_pass = hash_password("affiliate_dummy_pass")
                    try:
                        execute_statement("INSERT INTO users (username, password, email, referral_code, subscription_status) VALUES (:u, :p, :e, :rc, 'Affiliate')", params={"u": aff_name_clean, "p": fake_pass, "e": fake_email, "rc": aff_code})
                        st.success(f"Affiliate Created: Code **{aff_code}** is live!")
                    except Exception as e: st.error(f"Error (Code likely taken): {e}")

    elif page == "Dashboard":
        st.title("Financial Overview")
        st.caption(f"Welcome back, {c_name or 'Admin'}")
        def get_scalar(q, p):
            res = run_query(q, p)
            return res.iloc[0, 0] if not res.empty and res.iloc[0, 0] is not None else 0.0
        t_contracts = get_scalar("SELECT SUM(quoted_price) FROM projects WHERE user_id=:id", {"id": user_id})
        t_invoiced = get_scalar("SELECT SUM(amount) FROM invoices WHERE user_id=:id", {"id": user_id})
        t_collected = get_scalar("SELECT SUM(amount) FROM payments WHERE user_id=:id", {"id": user_id})
        remaining_to_invoice = t_contracts - t_invoiced; outstanding_ar = t_invoiced - t_collected
        c1, c2 = st.columns(2)
        with c1: metric_card("Total Contracts", f"${t_contracts:,.2f}", "Total Booked Work"); metric_card("Total Collected", f"${t_collected:,.2f}", "Cash in Bank")
        with c2: metric_card("Total Invoiced", f"${t_invoiced:,.2f}", f"Remaining: ${remaining_to_invoice:,.2f}"); metric_card("Outstanding AR", f"${outstanding_ar:,.2f}", "Unpaid Invoices")
        chart_data_pdf = {'Invoiced': t_invoiced, 'Collected': t_collected, 'Outstanding': outstanding_ar, 'Remaining': remaining_to_invoice}
        dash_metrics = {"Total Contracts": f"${t_contracts:,.2f}", "Total Invoiced": f"${t_invoiced:,.2f}", "Total Collected": f"${t_collected:,.2f}", "Remaining to Invoice": f"${remaining_to_invoice:,.2f}", "Outstanding AR": f"${outstanding_ar:,.2f}"}
        pdf_bytes = generate_dashboard_pdf(dash_metrics, c_name or "My Firm", logo, chart_data_pdf)
        st.download_button("📂 Download Dashboard Report (PDF)", pdf_bytes, f"Executive_Report_{datetime.date.today()}.pdf", "application/pdf")
        st.markdown("### Analysis")
        vc1, vc2 = st.columns(2)
        with vc1:
            st.markdown("##### Revenue Breakdown")
            chart_data = pd.DataFrame({'Category': ['Invoiced', 'Collected', 'Outstanding AR'], 'Amount': [t_invoiced, t_collected, outstanding_ar]})
            c = alt.Chart(chart_data).mark_bar().encode(x='Category', y='Amount', color=alt.Color('Category', scale=alt.Scale(scheme='tableau10'))).properties(height=250); st.altair_chart(c, theme="streamlit", use_container_width=True)
        with vc2:
            st.markdown("##### Contract Progress")
            pie_data = pd.DataFrame({'Status': ['Invoiced', 'Remaining'], 'Value': [t_invoiced, remaining_to_invoice]})
            base = alt.Chart(pie_data).encode(theta=alt.Theta("Value", stack=True)); pie = base.mark_arc(innerRadius=50).encode(color=alt.Color("Status", scale=alt.Scale(domain=['Invoiced', 'Remaining'], range=['#2B588D', '#DAA520'])), tooltip=["Status", "Value"]).properties(height=250); st.altair_chart(pie, theme="streamlit", use_container_width=True)
        st.markdown("---"); st.subheader("🔍 Project Deep-Dive")
        projs = run_query("SELECT id, name, client_name FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_id = int(projs[projs['name'] == p_choice]['id'].values[0])
            client_name = projs[projs['name'] == p_choice]['client_name'].values[0]
            p_row = run_query("SELECT quoted_price, start_date, duration, status FROM projects WHERE id=:id", {"id": p_id}).iloc[0]
            p_quoted = p_row['quoted_price'] or 0.0
            df_inv = run_query("SELECT issue_date, invoice_num, amount, description FROM invoices WHERE project_id=:pid", {"pid": p_id})
            df_pay = run_query("SELECT payment_date, amount, notes FROM payments WHERE project_id=:pid", {"pid": p_id})
            ledger = []
            for _, r in df_inv.iterrows(): ledger.append({'Date': r['issue_date'], 'Details': f"Invoice #{r['invoice_num']}", 'Charge': r['amount'], 'Payment': 0, 'Type': 'Inv'})
            for _, r in df_pay.iterrows(): ledger.append({'Date': r['payment_date'], 'Details': f"Payment ({r['notes']})", 'Charge': 0, 'Payment': r['amount'], 'Type': 'Pay'})
            df_ledger = pd.DataFrame(ledger)
            if not df_ledger.empty:
                df_ledger['Date'] = pd.to_datetime(df_ledger['Date'])
                df_ledger = df_ledger.sort_values(by='Date').reset_index(drop=True)
                df_ledger['Balance'] = (df_ledger['Charge'] - df_ledger['Payment']).cumsum()
                df_ledger['Date'] = df_ledger['Date'].dt.date
                tot_bill = df_ledger['Charge'].sum(); tot_paid = df_ledger['Payment'].sum(); curr_bal = tot_bill - tot_paid
                pc1, pc2 = st.columns(2)
                with pc1: metric_card("Project Value", f"${p_quoted:,.2f}")
                with pc2: metric_card("Current Balance", f"${curr_bal:,.2f}", "Outstanding")
                st.markdown("### Ledger History")
                col_pdf, col_tbl = st.columns([1,3])
                with col_pdf:
                    pdf_bytes = generate_statement_pdf(df_ledger, logo, {"name": c_name, "address": c_addr}, p_choice, client_name)
                    st.download_button("📄 Download Statement", pdf_bytes, f"statement_{p_choice}.pdf", "application/pdf")
                st.dataframe(df_ledger[['Date', 'Details', 'Charge', 'Payment', 'Balance']].style.format("{:.2f}", subset=['Charge', 'Payment', 'Balance']), use_container_width=True)
            else: st.info("No transactions yet.")
        else: st.info("No projects found.")

    elif page == "Projects":
        st.subheader("Manage Projects")
        with st.expander("Create New Project", expanded=False):
            with st.form("new_proj"):
                c1, c2 = st.columns(2)
                n = c1.text_input("Project Name"); c = c2.text_input("Client Name")
                q_str = c1.text_input("Quoted Price ($)", placeholder="0.00"); dur = c2.number_input("Duration (Days)", min_value=1)
                st.markdown("##### Addresses"); ac1, ac2 = st.columns(2)
                with ac1: b_street = st.text_input("Billing Street"); b_city = st.text_input("Billing City"); b_state = st.text_input("Billing State"); b_zip = st.text_input("Billing Zip")
                with ac2: s_street = st.text_input("Site Street"); s_city = st.text_input("Site City"); s_state = st.text_input("Site State"); s_zip = st.text_input("Site Zip")
                st.markdown("##### Details"); start_d = c1.date_input("Start Date"); po = c2.text_input("PO Number")
                status = c1.selectbox("Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"]); is_tax_exempt = c2.checkbox("Tax Exempt?"); scope = st.text_area("Scope")
                submitted = st.form_submit_button("Create Project")
                if submitted:
                    q = parse_currency(q_str)
                    execute_statement("INSERT INTO projects (user_id, name, client_name, quoted_price, start_date, duration, billing_street, billing_city, billing_state, billing_zip, site_street, site_city, site_state, site_zip, is_tax_exempt, po_number, status, scope_of_work) VALUES (:uid, :n, :c, :q, :sd, :d, :bs, :bc, :bst, :bz, :ss, :sc, :sst, :sz, :ite, :po, :stat, :scope)", params={"uid": user_id, "n": n, "c": c, "q": q, "sd": str(start_d), "d": dur, "bs": b_street, "bc": b_city, "bst": b_state, "bz": b_zip, "ss": s_street, "sc": s_city, "sst": s_state, "sz": s_zip, "ite": 1 if is_tax_exempt else 0, "po": po, "stat": status, "scope": scope})
                    st.success("Project Saved"); st.rerun()
        st.markdown("### Active Projects")
        projs = run_query("SELECT id, name, client_name, status, quoted_price FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            c_man_1, c_man_2 = st.columns([2, 2])
            with c_man_1:
                p_update = st.selectbox("Update Project", projs['name'], key="up_sel")
                new_stat = st.selectbox("New Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"], key="new_stat")
                if st.button("Update Status"):
                    pid = int(projs[projs['name'] == p_update]['id'].values[0])
                    execute_statement("UPDATE projects SET status=:s WHERE id=:id", {"s": new_stat, "id": pid}); st.success("Updated"); st.rerun()
            with c_man_2:
                p_del = st.selectbox("Delete Project", projs['name'], key="del_sel")
                if st.button("Delete", type="primary"):
                    pid = int(projs[projs['name'] == p_del]['id'].values[0])
                    execute_statement("DELETE FROM projects WHERE id=:id", {"id": pid}); execute_statement("DELETE FROM invoices WHERE project_id=:id", {"id": pid}); execute_statement("DELETE FROM payments WHERE project_id=:id", {"id": pid}); st.warning("Deleted"); st.rerun()
            st.dataframe(projs, use_container_width=True)
        else: st.info("No active projects.")

    elif page == "Invoices":
        st.subheader("Create Invoice")
        projs = run_query("SELECT * FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p = st.selectbox("Project", projs['name']); row = projs[projs['name']==p].iloc[0]
            tax_label = "Tax ($)" + (" - [EXEMPT]" if row['is_tax_exempt'] else "")
            
            with st.form("inv"):
                st.warning(f"Billing: **{row['name']}**"); inv_date = st.date_input("Date", value=datetime.date.today())
                a_str = st.text_input("Amount ($)", placeholder="0.00"); t_str = st.text_input(tax_label, placeholder="0.00"); d = st.text_area("Description")
                check_spelling = st.form_submit_button("✨ Check Spelling First")
                if check_spelling:
                    if not SPELLCHECK_AVAILABLE: st.warning("⚠️ Spellchecker library missing. Please add 'pyspellchecker' to requirements.txt")
                    else:
                        corrections = run_spell_check(d)
                        if corrections:
                            st.info("💡 Found possible typos:")
                            for wrong, right in corrections.items(): st.write(f"- **{wrong}** → _{right}_")
                        else: st.success("✅ No typos found!")
                verified = st.checkbox("I verify billing is correct"); submitted = st.form_submit_button("Generate Invoice")
                if submitted:
                    if verified:
                        a = parse_currency(a_str); t = parse_currency(t_str)
                        res_num = run_query("SELECT MAX(invoice_num) FROM invoices WHERE user_id=:id", {"id": user_id})
                        current_max = res_num.iloc[0, 0] if not res_num.empty and res_num.iloc[0, 0] is not None else 1000
                        num = current_max + 1
                        p_info = {k: row[k] for k in ['name', 'client_name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'site_street', 'site_city', 'site_state', 'site_zip', 'po_number']}
                        pdf = generate_pdf_invoice({'number': num, 'amount': a+t, 'tax': t, 'date': str(inv_date), 'description': d}, logo, {'name': c_name, 'address': c_addr}, p_info, terms)
                        st.session_state.pdf = pdf; file_name = f"{row['client_name']}_Invoice#{num}_{inv_date}.pdf"; st.session_state.inv_filename = file_name
                        execute_statement("INSERT INTO invoices (user_id, project_id, invoice_num, amount, issue_date, description, tax) VALUES (:uid, :pid, :num, :amt, :dt, :desc, :tax)", {"uid": user_id, "pid": int(row['id']), "num": int(num), "amt": a+t, "dt": str(inv_date), "desc": d, "tax": t}); st.success(f"Invoice #{num} Generated")
                    else: st.error("Please verify details.")
            if "pdf" in st.session_state:
                fname = st.session_state.get("inv_filename", "invoice.pdf")
                st.download_button("Download PDF", st.session_state.pdf, fname, "application/pdf")
            
            st.markdown("---")
            st.subheader("📜 Invoice History & Reprint")
            hist_inv = run_query("SELECT invoice_num, issue_date, amount, tax, description FROM invoices WHERE project_id=:pid ORDER BY invoice_num DESC", {"pid": int(row['id'])})
            if not hist_inv.empty:
                st.dataframe(hist_inv[['invoice_num', 'issue_date', 'amount', 'description']], use_container_width=True)
                c_rep1, c_rep2 = st.columns([3, 2])
                with c_rep1:
                    inv_to_print = st.selectbox("Select Invoice to Reprint", hist_inv['invoice_num'], key="reprint_sel")
                with c_rep2:
                    st.write(""); st.write("")
                    if inv_to_print:
                        rec = hist_inv[hist_inv['invoice_num'] == inv_to_print].iloc[0]
                        p_info_rep = {k: row[k] for k in ['name', 'client_name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'site_street', 'site_city', 'site_state', 'site_zip', 'po_number']}
                        
                        # FIX: Using 'terms' variable (which maps to 'terms_conditions')
                        pdf_rep = generate_pdf_invoice({'number': rec['invoice_num'], 'amount': rec['amount'], 'tax': rec['tax'], 'date': str(rec['issue_date']), 'description': rec['description']}, logo, {'name': c_name, 'address': c_addr}, p_info_rep, terms)
                        st.download_button(label=f"📥 Download PDF #{inv_to_print}", data=pdf_rep, file_name=f"Invoice_{rec['invoice_num']}_{row['client_name']}.pdf", mime="application/pdf")
            else:
                st.info("No past invoices for this project.")

    elif page == "Payments":
        st.subheader("Log Payment")
        projs = run_query("SELECT * FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p = st.selectbox("Project", projs['name']); row = projs[projs['name']==p].iloc[0]
            with st.form("pay_form", clear_on_submit=True):
                amt_str = st.text_input("Amount Received ($)", placeholder="0.00"); pay_date = st.date_input("Date"); notes = st.text_input("Notes (Check #)")
                verified_pay = st.checkbox("Confirm Payment"); submitted_pay = st.form_submit_button("Log Payment")
                if submitted_pay:
                    if verified_pay:
                        amt = parse_currency(amt_str)
                        execute_statement("INSERT INTO payments (user_id, project_id, amount, payment_date, notes) VALUES (:uid, :pid, :amt, :dt, :n)", {"uid": user_id, "pid": int(row['id']), "amt": amt, "dt": str(pay_date), "n": notes}); st.success("Payment Logged")
                    else: st.error("Please verify.")
            st.markdown("### Payment History")
            hist = run_query("SELECT payment_date, amount, notes FROM payments WHERE project_id=:pid", {"pid": int(row['id'])})
            st.dataframe(hist)

    elif page == "Settings":
        st.header("Settings")
        st.markdown(f"""<div class="referral-box"><h3>🚀 Refer & Earn</h3><p>Share code: <b>{my_code}</b></p><p>Active Referrals: <b>{active_referrals}</b> | Discount Earned: <b>{discount_percent_earned}%</b></p></div><br>""", unsafe_allow_html=True)
        if referred_by: st.success(f"✅ You are receiving a 10% Discount for being referred by: {referred_by}")
        st.info(f"Total Current Discount: {total_discount}%"); st.progress(min(total_discount, 100) / 100)
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or ""); ca = st.text_area("Address", value=c_addr or ""); t_cond = st.text_area("Terms", value=terms or ""); l = st.file_uploader("Update Logo")
            submitted_set = st.form_submit_button("Save Profile")
            if submitted_set:
                if l: lb = l.read(); execute_statement("UPDATE users SET company_name=:cn, company_address=:ca, logo_data=:ld, terms_conditions=:tc WHERE id=:uid", {"cn": cn, "ca": ca, "ld": lb, "tc": t_cond, "uid": user_id})
                else: execute_statement("UPDATE users SET company_name=:cn, company_address=:ca, terms_conditions=:tc WHERE id=:uid", {"cn": cn, "ca": ca, "tc": t_cond, "uid": user_id})
                st.success("Profile Updated"); st.rerun()
