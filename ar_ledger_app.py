import streamlit as st
import pandas as pd
import sqlite3
import datetime
import random
import string
import stripe 
import os
import tempfile
import bcrypt  
from fpdf import FPDF
import streamlit_authenticator as stauth

# --- 1. CONFIGURATION & B&B BRANDING ---
st.set_page_config(page_title="AR Ledger SaaS", layout="wide")

# Theme Colors: Navy (#2B588D) and Gold (#DAA520)
st.markdown("""
    <style>
    .stApp { background-color: #fcfcfc; }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] { background-color: #2B588D; }
    [data-testid="stSidebar"] * { color: white !important; }
    
    /* Metrics Styling */
    div[data-testid="metric-container"] {
        background-color: white; 
        padding: 15px; 
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
        border-left: 5px solid #DAA520; /* Gold Accent */
    }
    
    /* Button Styling */
    .stButton>button {
        background-color: #2B588D; 
        color: white; 
        border: 1px solid #DAA520;
    }
    .stButton>button:hover {
        background-color: #DAA520;
        color: white;
        border-color: #2B588D;
    }

    /* Headers */
    h1, h2, h3 { color: #2B588D; }
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
TERMS_URL = "https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf"

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
        quoted_price REAL, start_date TEXT, duration INTEGER,
        billing_address TEXT, site_address TEXT, 
        is_tax_exempt INTEGER DEFAULT 0, po_number TEXT,
        scope_of_work TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        number INTEGER, amount REAL, date TEXT, description TEXT, tax REAL DEFAULT 0
    )''')
    # Added 'notes' column for payment details
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        amount REAL, date TEXT, notes TEXT
    )''')
    conn.commit()

init_db()

# --- 3. HELPER FUNCTIONS ---
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

# CUSTOM PDF CLASS (Fixes Watermark Issue)
class InvoicePDF(FPDF):
    def footer(self):
        # Position at 1.5 cm from bottom
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, BB_WATERMARK, 0, 0, 'C')

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = InvoicePDF() # Use our custom class
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    
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
    
    pdf.ln(15); pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, f"INVOICE #{inv_data['number']}", ln=1)
    
    pdf.set_font("Arial", "B", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(100, 5, f"PROJECT: {project_info['name']}", ln=0)
    pdf.cell(0, 5, f"DATE: {inv_data['date']}", ln=1, align='R')
    
    pdf.ln(5); pdf.set_font("Arial", size=10)
    pdf.cell(100, 5, f"Client: {project_info['client_name']}", ln=1)
    if project_info.get('po_number'):
        pdf.cell(0, 5, f"PO #: {project_info['po_number']}", ln=1, align='R')
    
    pdf.ln(5)
    pdf.multi_cell(0, 5, f"Billing Addr: {project_info.get('billing_address', '')}")
    pdf.multi_cell(0, 5, f"Site Addr: {project_info.get('site_address', '')}")

    pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "DESCRIPTION:", ln=1)
    pdf.set_font("Arial", size=10); pdf.multi_cell(0, 5, inv_data['description'])
    
    pdf.ln(10)
    pdf.cell(0, 5, f"Subtotal: ${inv_data['amount'] - inv_data['tax']:,.2f}", ln=1, align='R')
    pdf.cell(0, 5, f"Tax: ${inv_data['tax']:,.2f}", ln=1, align='R')
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"TOTAL: ${inv_data['amount']:,.2f}", border="T", ln=1, align='R')
    
    if terms: 
        pdf.ln(15); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "TERMS & CONDITIONS:", ln=1)
        pdf.set_font("Arial", size=8); pdf.multi_cell(0, 4, terms)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

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

def create_stripe_customer(email, name):
    try:
        return stripe.Customer.create(email=email, name=name).id
    except: return None

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
if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if st.session_state["authentication_status"] is False or st.session_state["authentication_status"] is None:
    # --- LOGIN SCREEN ---
    if os.path.exists("bb_logo.png"):
        st.image("bb_logo.png", width=200)
    else:
        st.title("Balance & Build Consulting")

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
        st.header("Create New Account")
        with st.form("signup"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            e = st.text_input("Email")
            ref_code = st.text_input("Referral Code (Optional)")
            
            st.markdown("---")
            st.markdown(f"Please read the [Terms and Conditions]({TERMS_URL}) before signing up.")
            terms_agreed = st.checkbox("I acknowledge that I have read and agree to the Terms and Conditions.")
            
            if st.form_submit_button("Create Account"):
                if not terms_agreed:
                    st.error("You must agree to the Terms and Conditions to proceed.")
                elif u and p and e:
                    try:
                        if ref_code:
                            referrer = conn.execute("SELECT id FROM users WHERE referral_code=?", (ref_code,)).fetchone()
                            if referrer: conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE id=?", (referrer[0],))

                        h_p = hash_password(p)
                        cid = create_stripe_customer(e, u)
                        my_ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        
                        conn.execute("INSERT INTO users (username, password, email, stripe_customer_id, referral_code) VALUES (?,?,?,?,?)", 
                                     (u, h_p, e, cid, my_ref))
                        conn.commit()
                        st.success("Account Created! Please switch to Login tab.")
                    except Exception as err: st.error(f"Error: {err}")
                else:
                    st.warning("Please fill all fields")
else:
    # --- MAIN APP ---
    if 'user_id' not in st.session_state:
        u = st.session_state["username"]
        rec = conn.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username=?", (u,)).fetchone()
        if rec:
            st.session_state.user_id = rec[0]; st.session_state.sub_status = rec[1]; st.session_state.stripe_cid = rec[2]
        else:
            authenticator.logout(); st.rerun()
    
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
    
    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Invoices", "Payments", "Settings"])
    
    if page == "Dashboard":
        st.title("Executive Dashboard")
        if logo: st.image(logo, width=150)
        
        t_inv = conn.execute("SELECT SUM(amount) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        t_rec = conn.execute("SELECT SUM(amount) FROM payments WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Invoiced", f"${t_inv:,.2f}")
        c2.metric("Collected", f"${t_rec:,.2f}")
        c3.metric("Outstanding", f"${t_inv - t_rec:,.2f}")

    elif page == "Projects":
        st.subheader("Projects")
        with st.form("new_proj"):
            c1, c2 = st.columns(2)
            n = c1.text_input("Project Name")
            c = c2.text_input("Client Name")
            q = c1.number_input("Quoted Price ($)", min_value=0.0)
            dur = c2.number_input("Duration (Days)", min_value=1)
            
            s_addr = c1.text_input("Site Address")
            b_addr = c2.text_input("Billing Address")
            
            start_d = c1.date_input("Start Date")
            po = c2.text_input("PO Number (Optional)")
            
            is_tax_exempt = st.checkbox("Client is Tax Exempt?")
            scope = st.text_area("Scope of Work")
            
            # Using form_submit_button strictly
            if st.form_submit_button("Create Project"):
                conn.execute("""INSERT INTO projects 
                             (user_id, name, client_name, quoted_price, start_date, duration, 
                              billing_address, site_address, is_tax_exempt, po_number, scope_of_work) 
                             VALUES (?,?,?,?,?,?,?,?,?,?,?)""", 
                             (user_id, n, c, q, str(start_d), dur, b_addr, s_addr, 1 if is_tax_exempt else 0, po, scope))
                conn.commit()
                st.success("Project Saved"); st.rerun()
                
        st.dataframe(pd.read_sql_query("SELECT name, client_name, quoted_price, start_date, po_number FROM projects WHERE user_id=?", conn, params=(user_id,)))

    elif page == "Invoices":
        st.subheader("Invoicing")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            
            tax_label = "Tax ($)"
            if row['is_tax_exempt'] == 1: tax_label = "Tax ($) - [EXEMPT]"
            
            with st.form("inv"):
                a = st.number_input("Amount", min_value=0.0)
                t = st.number_input(tax_label, value=0.0) 
                d = st.text_area("Desc", value=row['scope_of_work'])
                
                if st.form_submit_button("Generate"):
                    num = (conn.execute("SELECT MAX(number) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 1000) + 1
                    pdf = generate_pdf_invoice(
                        {'number': num, 'amount': a+t, 'tax': t, 'date': str(datetime.date.today()), 'description': d}, 
                        logo, {'name': c_name, 'address': c_addr}, 
                        {'name': row['name'], 'client_name': row['client_name'], 'billing_address': row['billing_address'], 'site_address': row['site_address'], 'po_number': row['po_number']}, 
                        terms
                    )
                    st.session_state.pdf = pdf
                    conn.execute("INSERT INTO invoices (user_id, project_id, number, amount, date, description, tax) VALUES (?,?,?,?,?,?,?)", 
                                 (user_id, int(row['id']), num, a+t, str(datetime.date.today()), d, t))
                    conn.commit()
            
            if "pdf" in st.session_state: st.download_button("Download PDF", st.session_state.pdf, "inv.pdf")
    
    # --- NEW PAYMENTS TAB ---
    elif page == "Payments":
        st.subheader("Receive Payment")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id=?", conn, params=(user_id,))
        
        if not projs.empty:
            p = st.selectbox("Apply to Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            
            with st.form("pay_form"):
                amt = st.number_input("Payment Amount ($)", min_value=0.01)
                pay_date = st.date_input("Date Received")
                # Notes field for Invoice # or Check #
                notes = st.text_input("Notes (Invoice #, Check #, etc.)")
                
                if st.form_submit_button("Log Payment"):
                    conn.execute("INSERT INTO payments (user_id, project_id, amount, date, notes) VALUES (?,?,?,?,?)", 
                                 (user_id, int(row['id']), amt, str(pay_date), notes))
                    conn.commit()
                    st.success("Payment Logged Successfully")
                    st.rerun()
            
            # Show Payment History
            st.markdown("### Payment History")
            pay_hist = pd.read_sql_query("SELECT date, amount, notes FROM payments WHERE project_id=?", conn, params=(int(row['id']),))
            st.dataframe(pay_hist)

    elif page == "Settings":
        st.header("Company Settings")
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or "")
            ca = st.text_area("Address", value=c_addr or "")
            st.markdown("---")
            t_cond = st.text_area("Terms & Conditions (Appears on Invoice)", value=terms or "", height=150)
            l = st.file_uploader("Upload Logo")
            
            if st.form_submit_button("Save Settings"):
                lb = l.read() if l else logo
                conn.execute("UPDATE users SET company_name=?, company_address=?, logo_data=?, terms_conditions=? WHERE id=?", 
                             (cn, ca, lb, t_cond, user_id))
                conn.commit(); st.success("Settings Saved"); st.rerun()
    
    if st.sidebar.button("Logout"): authenticator.logout(); st.rerun()
    