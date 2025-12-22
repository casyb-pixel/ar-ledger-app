import streamlit as st
import pandas as pd
import sqlite3
import datetime
import smtplib
import random
import string
import stripe 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fpdf import FPDF
import matplotlib.pyplot as plt
import io
import altair as alt
import os
import zipfile
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities.hasher import Hasher
from streamlit_authenticator.utilities.exceptions import LoginError 
import bcrypt

# --- CONFIGURATION & STRIPE SETUP ---
st.set_page_config(page_title="AR Ledger App", layout="wide")

# STRIPE KEYS (READ FROM SECRETS.TOML)
if "STRIPE_LIVE_SECRET_KEY" in st.secrets and st.secrets["STRIPE_LIVE_SECRET_KEY"].startswith('sk_live'):
    stripe.api_key = st.secrets["STRIPE_LIVE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets["STRIPE_LIVE_PUBLISHABLE_KEY"]
    os.environ['STRIPE_SECRET_KEY'] = stripe.api_key
else:
    stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY", "sk_test_fallback")
    STRIPE_PUBLISHABLE_KEY = st.secrets.get("STRIPE_PUBLISHABLE_KEY", "pk_test_fallback")

STRIPE_PRICE_LOOKUP_KEY = "standard_monthly" 
BB_WATERMARK = "Powered by Balance & Build Consulting, LLC"
BB_LOGO_PATH = "bb_logo.png" 
DB_FILE = "ar_ledger.db"

# --- DATABASE CONNECTION ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

conn = get_db_connection()

# --- DATABASE TABLES ---
def init_db():
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, password TEXT, email TEXT,
        logo_data BLOB, terms_conditions TEXT,
        company_name TEXT, company_address TEXT, company_phone TEXT,
        subscription_status TEXT DEFAULT 'Inactive', 
        stripe_customer_id TEXT, stripe_subscription_id TEXT,
        referral_code TEXT UNIQUE, referral_count INTEGER DEFAULT 0
    )''')
    
    # Updated Projects Table
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, name TEXT, client_name TEXT,
        quoted_price REAL, start_date DATE, duration INTEGER,
        site_address TEXT, billing_address TEXT, 
        scope_of_work TEXT, priority INTEGER, status TEXT DEFAULT 'Active',
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # Updated Contacts Table
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, project_id INTEGER,
        name TEXT, email TEXT, phone TEXT,
        preferred_method TEXT, is_primary BOOLEAN DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, project_id INTEGER, number INTEGER,
        amount REAL, date DATE, description TEXT,
        tax REAL DEFAULT 0, discount REAL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, project_id INTEGER, amount REAL,
        date DATE, form TEXT, check_number TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    conn.commit()

init_db()

# --- HELPER FUNCTIONS ---
def generate_pdf_invoice(invoice_data, user_logo_data, company_info, project_info, terms):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 5, BB_WATERMARK, ln=1, align='C')
    
    if user_logo_data:
        temp_logo = f"temp_logo_{random.randint(0,999)}.png"
        with open(temp_logo, "wb") as f: f.write(user_logo_data)
        pdf.image(temp_logo, 10, 15, 33)
        os.remove(temp_logo)
            
    pdf.set_xy(120, 15)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 5, company_info.get('name', 'My Company'), ln=1, align='R')
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, company_info.get('address', ''), ln=1, align='R')
    
    pdf.ln(25)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 5, "BILL TO:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, project_info['client_name'], ln=1)
    pdf.multi_cell(0, 5, project_info['billing_address'])
    
    pdf.ln(10)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Invoice #{invoice_data['number']}", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, f"Date: {invoice_data['date']} | Project: {project_info['name']}", ln=1)
    pdf.cell(0, 10, f"Total Due: ${invoice_data['amount']:,.2f}", ln=1)
    
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 5, "Description / Scope of Work:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, invoice_data['description'])
    
    pdf.ln(15)
    pdf.set_font("Arial", "I", 8)
    pdf.multi_cell(0, 5, f"Terms: {terms}")
    
    buf = io.BytesIO()
    buf.write(pdf.output(dest='S').encode('latin1'))
    buf.seek(0)
    return buf

def get_user_data(user_id, table, extra=""):
    return pd.read_sql_query(f"SELECT * FROM {table} WHERE user_id = ? {extra}", conn, params=(user_id,))

# --- STRIPE LOGIC ---
def create_checkout_session(customer_id):
    try:
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        price_id = prices.data[0].id
        session = stripe.checkout.Session.create(
            customer=customer_id, payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription', subscription_data={'trial_period_days': 30},
            success_url='https://ar-ledger-app.streamlit.app/?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://ar-ledger-app.streamlit.app/'
        )
        return session.url, None
    except Exception as e: return None, str(e)

# --- AUTH & UI ---
credentials = load_credentials() # Assumes existing helper
authenticator = stauth.Authenticate(credentials, 'ar_ledger_cookie', 'velazco_key_beta_2025', 30)

if not st.session_state.get("authenticated"):
    authenticator.login(location='main')
    if st.session_state["authentication_status"]:
        username = st.session_state["username"]
        res = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (username,)).fetchone()
        st.session_state.update({"user_id": res[0], "sub_status": res[1], "stripe_cid": res[2], "authenticated": True})
        st.rerun()
else:
    # --- SUBSCRIPTION GATE ---
    if st.session_state.sub_status != 'Active':
        st.warning("Active Subscription Required")
        url, _ = create_checkout_session(st.session_state.stripe_cid)
        st.link_button("Start 30-Day Free Trial", url)
        if st.button("Check Status"):
            # logic to ping stripe and update db status
            st.rerun()
        st.stop()

    # --- MAIN APP ---
    user_id = st.session_state.user_id
    u_data = conn.execute("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=?", (user_id,)).fetchone()
    user_logo_data, comp_name, comp_addr, user_terms = u_data
    
    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Contacts", "Invoices", "Payments", "Settings"])

    if page == "Projects":
        st.subheader("Project Management")
        with st.expander("Add New Project"):
            with st.form("new_proj"):
                name = st.text_input("Project Name")
                client = st.text_input("Client Name")
                price = st.number_input("Quoted Price", min_value=0.0)
                site_addr = st.text_input("Project Site Address")
                bill_addr = st.text_area("Billing Address (For Invoices)")
                scope = st.text_area("Scope of Work")
                if st.form_submit_button("Save Project"):
                    conn.execute("INSERT INTO projects (user_id, name, client_name, quoted_price, site_address, billing_address, scope_of_work) VALUES (?,?,?,?,?,?,?)",
                                 (user_id, name, client, price, site_addr, bill_addr, scope))
                    conn.commit()
                    st.success("Project Created")
                    st.rerun()

    elif page == "Contacts":
        st.subheader("Project Contacts")
        projs = get_user_data(user_id, "projects")
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_id = int(projs[projs['name']==p_choice]['id'].values[0])
            with st.form("new_contact"):
                c_name = st.text_input("Name")
                c_email = st.text_input("Email")
                c_phone = st.text_input("Phone")
                method = st.selectbox("Preferred Contact Method", ["Email", "Phone", "Text"])
                if st.form_submit_button("Add Contact"):
                    conn.execute("INSERT INTO contacts (user_id, project_id, name, email, phone, preferred_method) VALUES (?,?,?,?,?,?)",
                                 (user_id, p_id, c_name, c_email, c_phone, method))
                    conn.commit()
                    st.success("Contact Added")

    elif page == "Invoices":
        st.subheader("Invoicing")
        projs = get_user_data(user_id, "projects")
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_row = projs[projs['name']==p_choice].iloc[0]
            with st.form("inv_form"):
                amt = st.number_input("Amount", min_value=0.01)
                desc = st.text_area("Invoice Description", value=p_row['scope_of_work'])
                if st.form_submit_button("Generate"):
                    inv_num = random.randint(1000, 9999)
                    inv_data = {'number': inv_num, 'amount': amt, 'date': datetime.date.today(), 'description': desc}
                    proj_info = {'name': p_row['name'], 'client_name': p_row['client_name'], 'billing_address': p_row['billing_address']}
                    pdf = generate_pdf_invoice(inv_data, user_logo_data, {'name': comp_name, 'address': comp_addr}, proj_info, user_terms)
                    st.download_button("Download PDF", pdf, f"Invoice_{inv_num}.pdf")

    # (Remaining Dashboard, Payments, Settings logic follows existing patterns)
