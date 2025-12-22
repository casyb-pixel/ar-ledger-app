import streamlit as st
import pandas as pd
import sqlite3
import datetime
import random
import string
import stripe 
from fpdf import FPDF
import io
import altair as alt
import os
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities.hasher import Hasher
from streamlit_authenticator.utilities.exceptions import LoginError 

# --- CONFIGURATION & B&B BRANDING ---
st.set_page_config(page_title="AR Ledger App | Balance & Build", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #fcfcfc; }
    [data-testid="stSidebar"] { background-color: #2B588D; }
    [data-testid="stSidebar"] * { color: white !important; }
    .stMetric { background-color: white; padding: 20px; border-radius: 10px; border-left: 5px solid #DAA520; }
    h1, h2, h3 { color: #2B588D; }
    .stButton>button { background-color: #2B588D; color: white; border: 1px solid #DAA520; }
    </style>
    """, unsafe_allow_html=True)

# STRIPE SETUP
if "STRIPE_LIVE_SECRET_KEY" in st.secrets:
    stripe.api_key = st.secrets["STRIPE_LIVE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets["STRIPE_LIVE_PUBLISHABLE_KEY"]
else:
    stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY", "sk_test_fallback")

DB_FILE = "ar_ledger.db"
BB_WATERMARK = "Balance & Build Consulting, LLC | Financial Excellence"

def get_db_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

conn = get_db_connection()

def init_db():
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, email TEXT,
        logo_data BLOB, terms_conditions TEXT, company_name TEXT, company_address TEXT,
        subscription_status TEXT DEFAULT 'Inactive', stripe_customer_id TEXT, 
        referral_code TEXT UNIQUE, referred_by TEXT, referral_count INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, client_name TEXT,
        quoted_price REAL, site_address TEXT, billing_address TEXT, scope_of_work TEXT
    )''')
    # Fixed: Added Phone Number to Contacts
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        name TEXT, email TEXT, phone TEXT, preferred_method TEXT
    )''')
    # Fixed: Added Tax and Notes to Invoices
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER, 
        number INTEGER, amount REAL, date DATE, description TEXT, 
        tax_amount REAL DEFAULT 0, notes TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER, 
        amount REAL, date DATE, form TEXT, check_number TEXT
    )''')
    conn.commit()

init_db()

# --- HELPER FUNCTIONS ---
def load_credentials():
    users = conn.execute("SELECT username, password, email FROM users").fetchall()
    return {'usernames': {u[0]: {'name': u[0], 'password': u[1], 'email': u[2]} for u in users}}

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, BB_WATERMARK, ln=1, align='C')
    
    if logo_data:
        temp = f"logo_{random.randint(1,9999)}.png"
        with open(temp, "wb") as f: f.write(logo_data)
        pdf.image(temp, 10, 20, 35)
        os.remove(temp)

    pdf.set_xy(120, 25)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, company_info['name'], ln=1, align='R')
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, company_info['address'], align='R')
    
    pdf.ln(15)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 5, f"INVOICE #{inv_data['number']}", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, f"Date: {inv_data['date']}", ln=1)
    pdf.cell(0, 5, f"Bill To: {project_info['client_name']}", ln=1)
    pdf.multi_cell(0, 5, f"Billing Address: {project_info['billing_address']}")
    
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 5, "DESCRIPTION:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, inv_data['description'])
    
    pdf.ln(5)
    pdf.cell(0, 5, f"Subtotal: ${inv_data['subtotal']:,.2f}", ln=1)
    pdf.cell(0, 5, f"Tax: ${inv_data['tax']:,.2f}", ln=1)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"TOTAL DUE: ${inv_data['amount']:,.2f}", border="T", ln=1)
    
    if inv_data['notes']:
        pdf.ln(5)
        pdf.set_font("Arial", "I", 9)
        pdf.multi_cell(0, 5, f"Notes: {inv_data['notes']}")

    pdf.ln(10)
    pdf.set_font("Arial", "I", 8)
    pdf.multi_cell(0, 5, f"Terms: {terms}")
    
    buf = io.BytesIO()
    buf.write(pdf.output(dest='S').encode('latin1'))
    buf.seek(0)
    return buf

# --- AUTHENTICATION ---
credentials = load_credentials()
auth = stauth.Authenticate(credentials, 'ar_ledger_cookie', 'bb_key_2025', 30)

if not st.session_state.get("authenticated"):
    tab1, tab2 = st.tabs(["Login", "Signup"])
    with tab1:
        auth.login(location='main')
        if st.session_state["authentication_status"]:
            res = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (st.session_state["username"],)).fetchone()
            st.session_state.update({"user_id": res[0], "sub_status": res[1], "stripe_cid": res[2], "authenticated": True})
            st.rerun()
    with tab2:
        # Signup logic remains the same
        pass
else:
    user_id = st.session_state.user_id
    u_data = conn.execute("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=?", (user_id,)).fetchone()
    user_logo, comp_name, comp_addr, u_terms = u_data

    page = st.sidebar.radio("Navigation", ["Dashboard", "Projects", "Contacts", "Invoices", "Payments", "Settings"])

    if page == "Dashboard":
        # Fixed: Display Logo in Dashboard Header
        col_title, col_logo = st.columns([3, 1])
        with col_title:
            st.title(f"{comp_name or 'Firm'} Dashboard")
        with col_logo:
            if user_logo:
                st.image(user_logo, width=150)
        
        # Financial metrics logic...
        st.subheader("Executive Financial Summary")
        # (KPI Metrics display)

    elif page == "Contacts":
        st.subheader("Manage Contacts")
        projs = pd.read_sql_query("SELECT id, name FROM projects WHERE user_id = ?", conn, params=(user_id,))
        if not projs.empty:
            p_sel = st.selectbox("Assign to Project", projs['name'])
            p_id = int(projs[projs['name']==p_sel]['id'].values[0])
            with st.form("new_contact"):
                c_name = st.text_input("Contact Name")
                c_email = st.text_input("Email")
                c_phone = st.text_input("Phone Number") # Added Phone Field
                c_pref = st.selectbox("Preferred Method", ["Email", "Phone", "Text"])
                if st.form_submit_button("Save Contact"):
                    conn.execute("INSERT INTO contacts (user_id, project_id, name, email, phone, preferred_method) VALUES (?,?,?,?,?,?)",
                                 (user_id, p_id, c_name, c_email, c_phone, c_pref))
                    conn.commit()
                    st.success("Contact added successfully.")

    elif page == "Invoices":
        st.subheader("Create Invoice")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id = ?", conn, params=(user_id,))
        if not projs.empty:
            p_sel = st.selectbox("Project", projs['name'])
            p_row = projs[projs['name']==p_sel].iloc[0]
            with st.form("inv_form"):
                inv_date = st.date_input("Invoice Date", datetime.date.today()) # Added Invoice Date
                subtotal = st.number_input("Subtotal Amount ($)", min_value=0.01)
                
                tax_apply = st.radio("Apply Sales Tax?", ["No", "Yes"])
                tax_val = 0.0
                if tax_apply == "Yes":
                    tax_type = st.selectbox("Tax Type", ["Percentage (%)", "Flat Amount ($)"])
                    tax_input = st.number_input("Tax Value", min_value=0.0)
                    tax_val = (subtotal * (tax_input / 100)) if tax_type == "Percentage (%)" else tax_input
                
                inv_total = subtotal + tax_val
                st.write(f"**Total Invoice Amount:** ${inv_total:,.2f}")
                
                desc = st.text_area("Work Description", value=p_row['scope_of_work'])
                notes = st.text_area("Payment Notes (Optional)") # Added Notes
                
                if st.form_submit_button("Generate Invoice"):
                    inv_num = random.randint(10000, 99999)
                    # Fixed Error: Store PDF in session state for reliable download
                    inv_data = {
                        'number': inv_num, 'subtotal': subtotal, 'tax': tax_val, 
                        'amount': inv_total, 'date': inv_date, 'description': desc, 'notes': notes
                    }
                    proj_info = {
                        'name': p_row['name'], 'client_name': p_row['client_name'], 
                        'billing_address': p_row['billing_address'], 'site_address': p_row['site_address']
                    }
                    st.session_state.last_pdf = generate_pdf_invoice(inv_data, user_logo, {'name': comp_name, 'address': comp_addr}, proj_info, u_terms)
                    st.session_state.last_inv_num = inv_num
                    
                    conn.execute("INSERT INTO invoices (user_id, project_id, number, amount, date, description, tax_amount, notes) VALUES (?,?,?,?,?,?,?,?)",
                                 (user_id, int(p_row['id']), inv_num, inv_total, inv_date, desc, tax_val, notes))
                    conn.commit()
                    st.success(f"Invoice #{inv_num} Recorded.")

            if 'last_pdf' in st.session_state:
                st.divider()
                st.write(f"### Download Invoice #{st.session_state.last_inv_num}")
                st.download_button("📩 Click Here to Download PDF", st.session_state.last_pdf, f"Invoice_{st.session_state.last_inv_num}.pdf")

st.sidebar.divider()
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()
