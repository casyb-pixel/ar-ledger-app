import streamlit as st
import pandas as pd
import sqlite3
import datetime
import random
import string
import stripe 
import os
import tempfile
import bcrypt  # standard hashing library
from fpdf import FPDF
import streamlit_authenticator as stauth

# --- 1. CONFIGURATION & STYLING (ALWAYS RUNS FIRST) ---
st.set_page_config(page_title="AR Ledger SaaS", layout="wide")

# Force the CSS to run immediately
st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    [data-testid="stSidebar"] { background-color: #2c3e50; }
    [data-testid="stSidebar"] * { color: white !important; }
    div[data-testid="metric-container"] {
        background-color: white; padding: 15px; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 5px solid #DAA520;
    }
    </style>
    """, unsafe_allow_html=True)

# --- STRIPE SETUP ---
if "STRIPE_SECRET_KEY" in st.secrets:
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets.get("STRIPE_PUBLISHABLE_KEY", "")
else:
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_fallback")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "pk_test_fallback")

STRIPE_PRICE_LOOKUP_KEY = "standard_monthly" 
BB_WATERMARK = "Powered by Balance & Build Consulting, LLC"
DB_FILE = "ar_ledger.db"

# --- 2. DATABASE ENGINE ---
def get_db_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

conn = get_db_connection()

def init_db():
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, email TEXT,
        logo_data BLOB, terms_conditions TEXT, company_name TEXT, company_address TEXT,
        company_phone TEXT, subscription_status TEXT DEFAULT 'Inactive', 
        stripe_customer_id TEXT, stripe_subscription_id TEXT,
        referral_code TEXT UNIQUE, referral_count INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, client_name TEXT,
        quoted_price REAL, start_date TEXT, scope_of_work TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        number INTEGER, amount REAL, date TEXT, description TEXT, tax REAL DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        amount REAL, date TEXT
    )''')
    conn.commit()

init_db()

# --- 3. HELPER FUNCTIONS ---
def hash_password(password):
    # FIXED: Uses standard bcrypt to avoid library version errors
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = FPDF()
    pdf.add_page()
    if logo_data:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(logo_data); tmp_path = tmp.name
            pdf.image(tmp_path, 10, 10, 35); os.unlink(tmp_path)
        except: pass

    pdf.set_xy(120, 15); pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 5, str(company_info.get('name', '')), ln=1, align='R')
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, str(company_info.get('address', '')), align='R')
    
    pdf.ln(15); pdf.set_font("Arial", "B", 16); pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 10, f"INVOICE #{inv_data['number']}", ln=1)
    
    pdf.set_font("Arial", "B", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(100, 5, f"PROJECT: {project_info['name']}", ln=0)
    pdf.cell(0, 5, f"DATE: {inv_data['date']}", ln=1, align='R')
    
    pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "DESCRIPTION:", ln=1)
    pdf.set_font("Arial", size=10); pdf.multi_cell(0, 5, inv_data['description'])
    
    pdf.ln(10)
    pdf.cell(0, 5, f"TOTAL: ${inv_data['amount']:,.2f}", border="T", ln=1, align='R')
    
    if terms: pdf.ln(10); pdf.set_font("Arial", size=8); pdf.multi_cell(0, 4, f"TERMS: {terms}")
    
    pdf.set_y(-15); pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 10, BB_WATERMARK, ln=0, align='C')
    return pdf.output(dest='S').encode('latin-1', 'replace')

def create_stripe_customer(email, name):
    try:
        return stripe.Customer.create(email=email, name=name).id
    except: return None

def create_checkout_session(customer_id):
    try:
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        if not prices.data: return None, "Price Not Found"
        session = stripe.checkout.Session.create(
            customer=customer_id, payment_method_types=['card'],
            line_items=[{'price': prices.data[0].id, 'quantity': 1}], mode='subscription',
            success_url='https://example.com/success', cancel_url='https://example.com/cancel'
        )
        return session.url, None
    except Exception as e: return None, str(e)

# --- 4. AUTHENTICATION ---
def load_credentials():
    c = conn.cursor()
    c.execute("SELECT username, password, email FROM users")
    users = c.fetchall()
    if not users: return {'usernames': {}}
    return {'usernames': {u[0]: {'name': u[0], 'password': u[1], 'email': u[2]} for u in users}}

credentials = load_credentials()
authenticator = stauth.Authenticate(credentials, 'ar_ledger_cookie_v2', 'bb_key_new', 1)

# --- 5. LOGIC FLOW ---

# Ensure session state is initialized
if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if st.session_state["authentication_status"] is False or st.session_state["authentication_status"] is None:
    # --- LOGIN / SIGNUP SCREEN ---
    st.title("Client AR Portal")
    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        authenticator.login(location='main')
        if st.session_state["authentication_status"]:
            u = st.session_state["username"]
            rec = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (u,)).fetchone()
            if rec:
                st.session_state.user_id = rec[0]
                st.session_state.sub_status = rec[1]
                st.session_state.stripe_cid = rec[2]
            st.rerun()
        elif st.session_state["authentication_status"] is False:
            st.error('Username/password is incorrect')
            
    with tab2:
        st.header("New Account")
        with st.form("signup"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            e = st.text_input("Email")
            if st.form_submit_button("Create Account"):
                if u and p and e:
                    try:
                        h_p = hash_password(p)
                        cid = create_stripe_customer(e, u)
                        conn.execute("INSERT INTO users (username, password, email, stripe_customer_id) VALUES (?,?,?,?)", (u, h_p, e, cid))
                        conn.commit()
                        st.success("Account Created! Please switch to Login tab.")
                    except Exception as err: st.error(f"Error: {err}")
                else:
                    st.warning("Please fill all fields")

else:
    # --- MAIN APP (AUTHENTICATED) ---
    if 'user_id' not in st.session_state:
        u = st.session_state["username"]
        rec = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (u,)).fetchone()
        if rec:
            st.session_state.user_id = rec[0]; st.session_state.sub_status = rec[1]; st.session_state.stripe_cid = rec[2]
        else:
            authenticator.logout()
            st.rerun()
    
    user_id = st.session_state.user_id
    
    if st.session_state.sub_status != 'Active' and st.session_state.stripe_cid:
        st.warning("⚠️ Trial Inactive")
        url, err = create_checkout_session(st.session_state.stripe_cid)
        if url: st.link_button("Start Subscription", url)
        if st.button("Simulate Payment (Dev Only)"):
            conn.execute("UPDATE users SET subscription_status='Active' WHERE id=?", (user_id,))
            conn.commit(); st.session_state.sub_status = 'Active'; st.rerun()
        if st.sidebar.button("Logout"): authenticator.logout(); st.rerun()
        st.stop()

    u_data = conn.execute("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=?", (user_id,)).fetchone()
    logo, c_name, c_addr, terms = u_data
    
    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Invoices", "Settings"])
    
    if page == "Dashboard":
        st.title("Executive Dashboard")
        if logo: st.image(logo, width=100)
        t_inv = conn.execute("SELECT SUM(amount) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        st.metric("Total Invoiced", f"${t_inv:,.2f}")

    elif page == "Projects":
        st.subheader("Projects")
        with st.form("np"):
            n = st.text_input("Project Name"); c = st.text_input("Client")
            q = st.number_input("Quoted Price"); s = st.text_area("Scope")
            if st.form_submit_button("Create"):
                conn.execute("INSERT INTO projects (user_id, name, client_name, quoted_price, scope_of_work, start_date) VALUES (?,?,?,?,?,?)", 
                             (user_id, n, c, q, s, str(datetime.date.today())))
                conn.commit(); st.success("Saved"); st.rerun()
        st.dataframe(pd.read_sql_query("SELECT name, client_name, quoted_price FROM projects WHERE user_id=?", conn, params=(user_id,)))

    elif page == "Invoices":
        st.subheader("Invoicing")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            p = st.selectbox("Project", projs['name']); row = projs[projs['name']==p].iloc[0]
            with st.form("inv"):
                a = st.number_input("Amount"); t = st.number_input("Tax"); d = st.text_area("Desc", value=row['scope_of_work'])
                if st.form_submit_button("Generate"):
                    num = (conn.execute("SELECT MAX(number) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 1000) + 1
                    pdf = generate_pdf_invoice({'number': num, 'amount': a+t, 'tax': t, 'date': str(datetime.date.today()), 'description': d}, logo, {'name': c_name, 'address': c_addr}, {'name': row['name'], 'client_name': row['client_name']}, terms)
                    st.session_state.pdf = pdf
                    conn.execute("INSERT INTO invoices (user_id, project_id, number, amount, date, description, tax) VALUES (?,?,?,?,?,?,?)", (user_id, int(row['id']), num, a+t, str(datetime.date.today()), d, t))
                    conn.commit()
            if "pdf" in st.session_state: st.download_button("Download PDF", st.session_state.pdf, "inv.pdf")

    elif page == "Settings":
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or ""); ca = st.text_area("Address", value=c_addr or "")
            l = st.file_uploader("Logo"); 
            if st.form_submit_button("Save"):
                lb = l.read() if l else logo
                conn.execute("UPDATE users SET company_name=?, company_address=?, logo_data=? WHERE id=?", (cn, ca, lb, user_id))
                conn.commit(); st.success("Saved"); st.rerun()
    
    if st.sidebar.button("Logout"): authenticator.logout(); st.rerun()
    