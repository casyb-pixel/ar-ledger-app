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
import zipfile
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities.hasher import Hasher
from streamlit_authenticator.utilities.exceptions import LoginError 

# --- CONFIGURATION & B&B BRANDING ---
st.set_page_config(page_title="AR Ledger App | Balance & Build", layout="wide")

# B&B Professional Palette: Navy (#2B588D) and Gold (#DAA520)
st.markdown("""
    <style>
    .stApp { background-color: #fcfcfc; }
    [data-testid="stSidebar"] { background-color: #2B588D; }
    [data-testid="stSidebar"] * { color: white !important; }
    .stMetric { 
        background-color: white; 
        padding: 20px; 
        border-radius: 10px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); 
        border-left: 5px solid #DAA520; 
    }
    h1, h2, h3 { color: #2B588D; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    .stButton>button { 
        background-color: #2B588D; 
        color: white; 
        border: 1px solid #DAA520;
        transition: 0.3s;
    }
    .stButton>button:hover { border: 1px solid white; color: #DAA520; }
    </style>
    """, unsafe_allow_html=True)

# STRIPE SETUP
if "STRIPE_LIVE_SECRET_KEY" in st.secrets and st.secrets["STRIPE_LIVE_SECRET_KEY"].startswith('sk_live'):
    stripe.api_key = st.secrets["STRIPE_LIVE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets["STRIPE_LIVE_PUBLISHABLE_KEY"]
else:
    stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY", "sk_test_fallback")
    STRIPE_PUBLISHABLE_KEY = st.secrets.get("STRIPE_PUBLISHABLE_KEY", "pk_test_fallback")

STRIPE_PRICE_LOOKUP_KEY = "standard_monthly" 
BB_WATERMARK = "Balance & Build Consulting, LLC | Financial Excellence"
DB_FILE = "ar_ledger.db"

# --- DATABASE ENGINE ---
def get_db_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

conn = get_db_connection()

def init_db():
    c = conn.cursor()
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, email TEXT,
        logo_data BLOB, terms_conditions TEXT, company_name TEXT, company_address TEXT,
        subscription_status TEXT DEFAULT 'Inactive', stripe_customer_id TEXT, 
        stripe_subscription_id TEXT, referral_code TEXT UNIQUE, referral_count INTEGER DEFAULT 0,
        accepted_terms BOOLEAN DEFAULT 0
    )''')
    # Projects Table - Updated with Site/Billing Address & Scope
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, client_name TEXT,
        quoted_price REAL, start_date DATE, site_address TEXT, billing_address TEXT, 
        scope_of_work TEXT, status TEXT DEFAULT 'Active'
    )''')
    # Contacts Table - Updated with Preferred Method
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        name TEXT, email TEXT, phone TEXT, preferred_method TEXT, is_primary BOOLEAN DEFAULT 0
    )''')
    # Invoices Table
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER, 
        number INTEGER, amount REAL, date DATE, description TEXT
    )''')
    # Payments Table
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER, 
        amount REAL, date DATE, form TEXT, check_number TEXT
    )''')
    # Audit Logs
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, timestamp DATETIME
    )''')
    conn.commit()

init_db()

# --- REUSABLE MODULES ---
def load_credentials():
    users = conn.execute("SELECT username, password, email FROM users").fetchall()
    return {'usernames': {u[0]: {'name': u[0], 'password': u[1], 'email': u[2]} for u in users}}

def generate_pdf_invoice(invoice_data, user_logo_data, company_info, project_info, terms):
    pdf = FPDF()
    pdf.add_page()
    # B&B Branding Header
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, BB_WATERMARK, ln=1, align='C')
    
    if user_logo_data:
        temp = f"logo_{random.randint(1,9999)}.png"
        with open(temp, "wb") as f: f.write(user_logo_data)
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
    pdf.cell(0, 5, "BILL TO:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, project_info['client_name'], ln=1)
    pdf.multi_cell(0, 5, project_info['billing_address'])
    
    pdf.ln(10)
    pdf.set_fill_color(43, 88, 141)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f" INVOICE #{invoice_data['number']}", ln=1, fill=True)
    
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", size=10)
    pdf.ln(5)
    pdf.cell(0, 5, f"Date: {invoice_data['date']}", ln=1)
    pdf.cell(0, 5, f"Project Site: {project_info['site_address']}", ln=1)
    
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 5, "DESCRIPTION / SCOPE OF WORK:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, invoice_data['description'])
    
    pdf.ln(15)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"TOTAL DUE: ${invoice_data['amount']:,.2f}", border="T", ln=1)
    
    pdf.ln(20)
    pdf.set_font("Arial", "I", 8)
    pdf.multi_cell(0, 5, f"Standard Terms: {terms}")
    
    buf = io.BytesIO()
    buf.write(pdf.output(dest='S').encode('latin1'))
    buf.seek(0)
    return buf

# --- AUTHENTICATION ---
credentials = load_credentials()
auth = stauth.Authenticate(credentials, 'ar_ledger_cookie', 'bb_key_2025', 30)

if not st.session_state.get("authenticated"):
    tab1, tab2 = st.tabs(["Firm Login", "New Firm Signup"])
    with tab1:
        auth.login(location='main')
        if st.session_state["authentication_status"]:
            res = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (st.session_state["username"],)).fetchone()
            st.session_state.update({"user_id": res[0], "sub_status": res[1], "stripe_cid": res[2], "authenticated": True})
            st.rerun()
    with tab2:
        # Signup logic implementation...
        pass
else:
    # --- SUBSCRIPTION GATE ---
    if st.session_state.sub_status != 'Active':
        st.info("💎 Welcome to Balance & Build AR Ledger. Activate your trial to begin.")
        # Create Stripe Session Logic...
        st.stop()

    user_id = st.session_state.user_id
    u_data = conn.execute("SELECT logo_data, company_name, company_address, terms_conditions, referral_code, referral_count FROM users WHERE id=?", (user_id,)).fetchone()
    user_logo, comp_name, comp_addr, u_terms, my_ref_code, my_ref_count = u_data
    
    st.sidebar.title("B&B AR Ledger")
    page = st.sidebar.radio("Main Menu", ["Dashboard", "Projects", "Contacts", "Invoices", "Payments", "Reports", "Settings", "Help"])

    # --- DASHBOARD & ANALYTICS ---
    if page == "Dashboard":
        
        st.subheader(f"Financial Summary for {comp_name or 'the Firm'}")
        
        inv_df = pd.read_sql_query("SELECT amount FROM invoices WHERE user_id = ?", conn, params=(user_id,))
        pay_df = pd.read_sql_query("SELECT amount FROM payments WHERE user_id = ?", conn, params=(user_id,))
        
        total_in = inv_df['amount'].sum() if not inv_df.empty else 0.0
        total_col = pay_df['amount'].sum() if not pay_df.empty else 0.0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Gross Billed", f"${total_in:,.2f}")
        c2.metric("Cash Collected", f"${total_col:,.2f}")
        c3.metric("Net Receivables", f"${total_in - total_col:,.2f}")
        
        st.divider()
        st.write("### Active Project Financials")
        projs = pd.read_sql_query("SELECT id, name, client_name, quoted_price, scope_of_work FROM projects WHERE user_id = ?", conn, params=(user_id,))
        for _, p in projs.iterrows():
            with st.expander(f"Project: {p['name']} | Client: {p['client_name']}"):
                p_id = p['id']
                p_invoiced = conn.execute("SELECT SUM(amount) FROM invoices WHERE project_id = ?", (p_id,)).fetchone()[0] or 0.0
                p_paid = conn.execute("SELECT SUM(amount) FROM payments WHERE project_id = ?", (p_id,)).fetchone()[0] or 0.0
                
                col_a, col_b = st.columns(2)
                col_a.write(f"**Quoted Budget:** ${p['quoted_price']:,.2f}")
                col_a.write(f"**Remaining to Invoice:** ${p['quoted_price'] - p_invoiced:,.2f}")
                col_b.write(f"**Currently Owed:** ${p_invoiced - p_paid:,.2f}")
                st.info(f"**Scope:** {p['scope_of_work']}")

    # --- PROJECT MANAGEMENT (NEW FIELDS) ---
    elif page == "Projects":
        st.subheader("Project Inventory")
        with st.expander("➕ Initialize New Project", expanded=True):
            with st.form("new_p"):
                c1, c2 = st.columns(2)
                p_name = c1.text_input("Project Display Name")
                p_client = c2.text_input("Client/Entity Name")
                p_site = c1.text_input("Project Site Physical Address")
                p_bill = c2.text_area("Client Billing Address (as it appears on Invoice)")
                p_scope = st.text_area("Detailed Scope of Work")
                p_quote = st.number_input("Total Contract Value ($)", min_value=0.0)
                if st.form_submit_button("Confirm Project Setup"):
                    conn.execute("INSERT INTO projects (user_id, name, client_name, site_address, billing_address, scope_of_work, quoted_price) VALUES (?,?,?,?,?,?,?)",
                                 (user_id, p_name, p_client, p_site, p_bill, p_scope, p_quote))
                    conn.commit()
                    st.success("Project database updated.")
                    st.rerun()

    # --- CONTACTS (PREFERRED METHOD) ---
    elif page == "Contacts":
        st.subheader("Entity Contacts")
        projs = pd.read_sql_query("SELECT id, name FROM projects WHERE user_id = ?", conn, params=(user_id,))
        if not projs.empty:
            p_sel = st.selectbox("Assign Contact to Project", projs['name'])
            p_id = int(projs[projs['name']==p_sel]['id'].values[0])
            with st.form("new_c"):
                c_name = st.text_input("Full Name")
                c_email = st.text_input("Email")
                c_pref = st.selectbox("Preferred Communication Method", ["Email", "Phone", "Text Message", "Direct Mail"])
                if st.form_submit_button("Save Contact"):
                    conn.execute("INSERT INTO contacts (user_id, project_id, name, email, preferred_method) VALUES (?,?,?,?,?)",
                                 (user_id, p_id, c_name, c_email, c_pref))
                    conn.commit()
                    st.success("Contact logged.")

    # --- INVOICING MODULE ---
    elif page == "Invoices":
        st.subheader("Revenue Generation")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id = ?", conn, params=(user_id,))
        if not projs.empty:
            p_sel = st.selectbox("Select Project for Billing", projs['name'])
            p_row = projs[projs['name']==p_sel].iloc[0]
            with st.form("inv"):
                inv_amt = st.number_input("Invoice Amount", min_value=0.01)
                inv_desc = st.text_area("Line Item Description", value=p_row['scope_of_work'])
                if st.form_submit_button("Generate Official Invoice"):
                    inv_num = random.randint(10000, 99999)
                    pdf = generate_pdf_invoice({'number': inv_num, 'amount': inv_amt, 'date': datetime.date.today(), 'description': inv_desc},
                                               user_logo, {'name': comp_name, 'address': comp_addr},
                                               {'name': p_row['name'], 'client_name': p_row['client_name'], 'billing_address': p_row['billing_address'], 'site_address': p_row['site_address']},
                                               u_terms)
                    conn.execute("INSERT INTO invoices (user_id, project_id, number, amount, date, description) VALUES (?,?,?,?,?,?)",
                                 (user_id, int(p_row['id']), inv_num, inv_amt, datetime.date.today(), inv_desc))
                    conn.commit()
                    st.download_button("📩 Download Professional Invoice", pdf, f"Invoice_{inv_num}.pdf")

    # --- REPORTING & EXPORTS ---
    elif page == "Reports":
        
        st.subheader("Financial Integrity Reporting")
        rpt = st.segmented_control("Report Type", ["Aging Report", "Project Statement", "Audit Logs"])
        
        if rpt == "Aging Report":
            # Aging logic with 30/60/90 buckets...
            inv_df = pd.read_sql_query("SELECT date, amount FROM invoices WHERE user_id = ?", conn, params=(user_id,))
            if not inv_df.empty:
                inv_df['date'] = pd.to_datetime(inv_df['date'])
                inv_df['age'] = (pd.Timestamp.now() - inv_df['date']).dt.days
                st.altair_chart(alt.Chart(inv_df).mark_bar(color='#DAA520').encode(x='age', y='amount'))
                st.download_button("Export Aging Data (CSV)", inv_df.to_csv(), "ar_aging.csv")

        elif rpt == "Project Statement":
            # Filtered project statement logic...
            st.info("Project Statements compile all invoices and payments for a specific job into a single export.")
            
    # --- SETTINGS & BACKUPS ---
    elif page == "Settings":
        st.info(f"🎁 Referral Network Status: {my_ref_count} Successes | Your Code: {my_ref_code}")
        with st.form("setup"):
            n_name = st.text_input("Firm Name", value=comp_name)
            n_addr = st.text_area("Firm Physical Address", value=comp_addr)
            n_logo = st.file_uploader("Upload New Logo (BLOB Persistent)", type=['png', 'jpg'])
            if st.form_submit_button("Synchronize Firm Profile"):
                logo_blob = n_logo.read() if n_logo else user_logo
                conn.execute("UPDATE users SET company_name=?, company_address=?, logo_data=? WHERE id=?", (n_name, n_addr, logo_blob, user_id))
                conn.commit()
                st.rerun()

st.sidebar.divider()
if st.sidebar.button("Logout & Secure Session"):
    st.session_state.clear()
    st.rerun()
