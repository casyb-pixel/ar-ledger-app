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

# Set Matplotlib to non-interactive mode
matplotlib.use('Agg')

# --- 1. CONFIGURATION & BRANDING ---
st.set_page_config(page_title="ProgressBill Pro", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #f4f6f9; }
    [data-testid="stSidebar"] { background-color: #2B588D; }
    [data-testid="stSidebar"] * { color: white !important; }
    div[data-testid="metric-container"] {
        background-color: white; padding: 20px; border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 6px solid #DAA520; text-align: center;
    }
    h1, h2, h3 { color: #2B588D; font-family: 'Helvetica', sans-serif; }
    .stButton>button {
        background-color: #2B588D; color: white; border: 1px solid #DAA520; border-radius: 5px;
    }
    .stButton>button:hover {
        background-color: #DAA520; color: white; border-color: #2B588D;
    }
    .stAlert { border: 1px solid #DAA520; }
    .referral-box {
        padding: 20px; background-color: #eef2f5; border-radius: 10px; border: 1px dashed #2B588D; text-align: center;
    }
    /* HIDDEN ELEMENTS - Removed 'header' so mobile menu works */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
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
BASE_PRICE = 29.99 
BB_WATERMARK = "ProgressBill Pro | Powered by Balance & Build Consulting"
TERMS_URL = "https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf"

# --- 2. DATABASE ENGINE (NULL POOL MODE) ---
@st.cache_resource
def get_engine():
    try:
        db_url = st.secrets["connections"]["supabase"]["url"]
        return create_engine(db_url, poolclass=NullPool)
    except Exception as e:
        st.error(f"Database Connection Failed: {e}")
        return None

engine = get_engine()

def run_query(query, params=None):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=params)
    except Exception as e:
        return pd.DataFrame() 

def execute_statement(query, params=None):
    try:
        with engine.begin() as conn: 
            conn.execute(text(query), params)
    except Exception as e:
        st.error(f"Database Error: {e}")
        raise e

def init_db():
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

# --- 3. HELPER FUNCTIONS ---
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
    """Cleans user input (removes $ and ,) and converts to float."""
    if not value: return 0.0
    if isinstance(value, (int, float)): return float(value)
    # Remove '$' and ',' and spaces, then convert
    clean = str(value).replace('$', '').replace(',', '').strip()
    try:
        return float(clean)
    except:
        return 0.0

# --- PDF GENERATOR CLASS ---
class BB_PDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, BB_WATERMARK, 0, 0, 'C')

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = BB_PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # FIXED LOGO HANDLING (AUTO-CONVERT TO PNG)
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name
            pdf.image(tmp_path, 10, 10, 35)
            os.unlink(tmp_path)
        except: pass
        
    pdf.set_xy(120, 15); pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 5, str(company_info.get('name', '')), ln=1, align='R')
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 5, str(company_info.get('address', '')), align='R')
    pdf.set_xy(120, 35)
    pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, f"INVOICE #{inv_data['number']}", ln=1, align='R')
    pdf.set_font("Arial", "B", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, f"DATE: {inv_data['date']}", ln=1, align='R')
    if project_info.get('po_number'): pdf.cell(0, 5, f"PO #: {project_info['po_number']}", ln=1, align='R')
    pdf.set_xy(10, 60); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "BILL TO:", ln=1)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, f"{project_info['client_name']}", ln=1)
    if project_info.get('billing_street'):
        pdf.cell(0, 5, f"{project_info['billing_street']}", ln=1)
        pdf.cell(0, 5, f"{project_info['billing_city']}, {project_info['billing_state']} {project_info['billing_zip']}", ln=1)
    right_x = 110; current_y = 60; pdf.set_xy(right_x, current_y)
    pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "PROJECT SITE:"); current_y += 5; pdf.set_xy(right_x, current_y)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, f"{project_info['name']}")
    if project_info.get('site_street'):
        current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, f"{project_info['site_street']}")
        current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, f"{project_info['site_city']}, {project_info['site_state']} {project_info['site_zip']}")
    pdf.set_xy(10, 95); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "DESCRIPTION:", ln=1)
    pdf.set_font("Arial", size=10); pdf.multi_cell(0, 5, inv_data['description'])
    pdf.ln(10)
    pdf.cell(0, 5, f"Subtotal: ${inv_data['amount'] - inv_data['tax']:,.2f}", ln=1, align='R')
    pdf.cell(0, 5, f"Tax: ${inv_data['tax']:,.2f}", ln=1, align='R')
    pdf.set_font("Arial", "B", 12); pdf.cell(0, 10, f"TOTAL: ${inv_data['amount']:,.2f}", border="T", ln=1, align='R')
    if terms: 
        pdf.ln(15); pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "TERMS & CONDITIONS:", ln=1)
        pdf.set_font("Arial", size=8); pdf.multi_cell(0, 4, terms)
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_statement_pdf(ledger_df, logo_data, company_info, project_name, client_name):
    pdf = BB_PDF()
    pdf.add_page()
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name
            pdf.image(tmp_path, 10, 10, 35)
            os.unlink(tmp_path)
        except: pass
    pdf.set_xy(120, 15); pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141)
    # CHANGED FROM "STATEMENT OF ACCOUNT" TO "PROJECT STATEMENT"
    pdf.cell(0, 10, "PROJECT STATEMENT", ln=1, align='R')
    pdf.set_font("Arial", size=10); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, f"Date: {datetime.date.today()}", ln=1, align='R')
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12); pdf.cell(0, 5, f"Project: {project_name}", ln=1)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, f"Client: {client_name}", ln=1)
    pdf.ln(10)
    # Table Header (Navy Blue)
    pdf.set_fill_color(43, 88, 141); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 8, "Date", 1, 0, 'C', 1); pdf.cell(80, 8, "Description", 1, 0, 'L', 1)
    pdf.cell(25, 8, "Charge", 1, 0, 'R', 1); pdf.cell(25, 8, "Payment", 1, 0, 'R', 1)
    pdf.cell(30, 8, "Balance", 1, 1, 'R', 1)
    # Rows
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=9)
    fill = False
    for index, row in ledger_df.iterrows():
        if fill: pdf.set_fill_color(240, 240, 240)
        else: pdf.set_fill_color(255, 255, 255)
        pdf.cell(30, 8, str(row['Date']), 1, 0, 'C', fill)
        pdf.cell(80, 8, str(row['Details'])[:40], 1, 0, 'L', fill)
        pdf.cell(25, 8, f"${row['Charge']:,.2f}", 1, 0, 'R', fill)
        pdf.cell(25, 8, f"${row['Payment']:,.2f}", 1, 0, 'R', fill)
        pdf.cell(30, 8, f"${row['Balance']:,.2f}", 1, 1, 'R', fill)
        fill = not fill
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_dashboard_pdf(metrics, company_name, logo_data, chart_data):
    pdf = BB_PDF()
    pdf.add_page()
    
    # --- HEADER SECTION ---
    pdf.set_fill_color(43, 88, 141) # Navy Blue
    pdf.rect(0, 0, 210, 40, 'F')
    
    # FIXED LOGO HANDLING (Different Coordinates for Dashboard)
    if logo_data:
        try:
            image = Image.open(io.BytesIO(logo_data))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name
            pdf.image(tmp_path, 10, 8, 25) # Note the coordinates 10, 8, 25
            os.unlink(tmp_path)
        except: pass
    
    pdf.set_xy(40, 10)
    pdf.set_font("Arial", "B", 20); pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, "EXECUTIVE FINANCIAL REPORT", ln=1)
    pdf.set_xy(40, 20)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"{company_name} | Date: {datetime.date.today()}", ln=1)
    
    pdf.ln(20)
    
    # --- METRICS TABLE ---
    pdf.set_text_color(43, 88, 141); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Key Performance Indicators", ln=1)
    pdf.ln(2)
    
    pdf.set_fill_color(218, 165, 32); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 11)
    pdf.cell(100, 10, "Metric Category", 1, 0, 'L', 1)
    pdf.cell(60, 10, "Value", 1, 1, 'R', 1)
    
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=11)
    fill = False
    for key, value in metrics.items():
        if fill: pdf.set_fill_color(245, 245, 245)
        else: pdf.set_fill_color(255, 255, 255)
        pdf.cell(100, 10, key, 1, 0, 'L', fill)
        pdf.cell(60, 10, value, 1, 1, 'R', fill)
        fill = not fill
        
    pdf.ln(15)
    
    # --- VISUALS SECTION ---
    pdf.set_text_color(43, 88, 141); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Visual Analysis", ln=1)
    
    if chart_data:
        # Chart 1: Revenue Breakdown (Bar) - Only if data exists
        total_rev = chart_data['Invoiced'] + chart_data['Collected'] + chart_data['Outstanding']
        
        if total_rev > 0:
            plt.figure(figsize=(6, 4))
            categories = ['Invoiced', 'Collected', 'Outstanding AR']
            values = [chart_data['Invoiced'], chart_data['Collected'], chart_data['Outstanding']]
            colors = ['#2B588D', '#28a745', '#DAA520']
            plt.bar(categories, values, color=colors)
            plt.title('Revenue Distribution', color='#2B588D')
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_chart1:
                plt.savefig(tmp_chart1.name, format='png', bbox_inches='tight')
                pdf.image(tmp_chart1.name, x=10, y=pdf.get_y() + 5, w=90)
                os.unlink(tmp_chart1.name)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.text(x=20, y=pdf.get_y() + 20, txt="No financial activity recorded yet.")

        # Chart 2: Contract Status (Pie) - Only if sum > 0
        pie_sizes = [chart_data['Invoiced'], chart_data['Remaining']]
        
        if sum(pie_sizes) > 0:
            plt.clf()
            plt.figure(figsize=(6, 4))
            labels = ['Invoiced', 'Remaining']
            plt.pie(pie_sizes, labels=labels, autopct='%1.1f%%', colors=['#2B588D', '#eef2f5'], startangle=90)
            plt.title('Contract Progress', color='#2B588D')
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_chart2:
                plt.savefig(tmp_chart2.name, format='png', bbox_inches='tight')
                pdf.image(tmp_chart2.name, x=110, y=pdf.get_y() + 5, w=90)
                os.unlink(tmp_chart2.name)
        else:
            pdf.set_font("Arial", "I", 10)
            pdf.text(x=130, y=pdf.get_y() + 20, txt="No contracts active.")

    return pdf.output(dest='S').encode('latin-1', 'replace')

def create_checkout_session(customer_id, discount_percent):
    try:
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        if not prices.data: return None, "Price Not Found"
        session_args = {
            'customer': customer_id, 'payment_method_types': ['card'],
            'line_items': [{'price': prices.data[0].id, 'quantity': 1}],
            'mode': 'subscription', 'success_url': 'https://example.com/success', 'cancel_url': 'https://example.com/cancel'
        }
        session = stripe.checkout.Session.create(**session_args)
        return session.url, None
    except Exception as e: return None, str(e)

def create_stripe_customer(email, name):
    try: return stripe.Customer.create(email=email, name=name).id
    except: return None

# --- 4. AUTHENTICATION ---
if 'user_id' not in st.session_state: st.session_state.user_id = None

if st.session_state.user_id is None:
    if os.path.exists("bb_logo.png"): st.image("bb_logo.png", width=200)
    else:
        st.title("ProgressBill Pro")
        st.caption("Powered by Balance & Build Consulting")

    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                df = run_query("SELECT id, password, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE username=:u", params={"u": u})
                if not df.empty:
                    rec = df.iloc[0]
                    if check_password(p, rec['password']):
                        st.session_state.user_id = int(rec['id'])
                        st.session_state.sub_status = rec['subscription_status']
                        st.session_state.stripe_cid = rec['stripe_customer_id']
                        st.session_state.created_at = rec['created_at']
                        st.session_state.my_ref_code = rec['referral_code']
                        st.success("Login successful!"); st.rerun()
                    else: st.error("Incorrect password")
                else: st.error("Username not found")

    with tab2:
        st.header("Create New Account"); st.caption("Start your 30-Day Free Trial")
        with st.form("signup"):
            u = st.text_input("Username"); p = st.text_input("Password", type="password"); e = st.text_input("Email")
            ref_input = st.text_input("Referral Code (Got one?)")
            st.markdown("---"); st.markdown(f"Please read the [Terms and Conditions]({TERMS_URL}) before signing up.")
            terms_agreed = st.checkbox("I acknowledge that I have read and agree to the Terms and Conditions.", value=False)
            submitted_sign = st.form_submit_button("Create Account")
            if submitted_sign:
                if not terms_agreed: st.error("You must agree to the Terms and Conditions.")
                elif u and p and e:
                    try:
                        check = run_query("SELECT id FROM users WHERE username=:u", params={"u": u})
                        if not check.empty: st.error("Username already taken.")
                        else:
                            h_p = hash_password(p); cid = create_stripe_customer(e, u)
                            my_ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                            today_str = str(datetime.date.today())
                            if ref_input:
                                execute_statement("UPDATE users SET referral_count = referral_count + 1 WHERE referral_code=:c", params={"c": ref_input})
                            execute_statement("""
                                INSERT INTO users (username, password, email, stripe_customer_id, referral_code, created_at, subscription_status, referred_by) 
                                VALUES (:u, :p, :e, :cid, :rc, :ca, 'Trial', :rb)
                            """, params={"u": u, "p": h_p, "e": e, "cid": cid, "rc": my_ref_code, "ca": today_str, "rb": ref_input})
                            st.success("Account Created! Please switch to Login tab.")
                    except Exception as err: st.error(f"Error: {err}")
                else: st.warning("Please fill all fields")

else:
    user_id = st.session_state.user_id
    
    df_user = run_query("SELECT subscription_status, created_at, referral_code FROM users WHERE id=:id", params={"id": user_id})
    if df_user.empty: st.session_state.clear(); st.rerun()
    status, created_at_str, my_code = df_user.iloc[0]['subscription_status'], df_user.iloc[0]['created_at'], df_user.iloc[0]['referral_code']
    
    active_referrals, discount_percent = get_referral_stats(my_code)
    days_left = 0; trial_active = False
    if status == 'Trial' and created_at_str:
        try:
            start_date = datetime.datetime.strptime(created_at_str, '%Y-%m-%d').date()
            days_left = 30 - (datetime.date.today() - start_date).days
            if days_left > 0: trial_active = True
        except: pass

    if status != 'Active' and not trial_active:
        if discount_percent >= 100:
            st.balloons(); st.success("🎉 You have earned FREE ACCESS with 10+ Referrals!")
            if st.button("Activate Free Lifetime Access"):
                execute_statement("UPDATE users SET subscription_status='Active' WHERE id=:id", params={"id": user_id})
                st.session_state.sub_status = 'Active'; st.rerun()
        else:
            st.warning(f"⚠️ Trial Expired. You have {active_referrals} Active Referrals ({discount_percent}% Discount).")
            new_price = BASE_PRICE * (1 - (discount_percent/100))
            st.info(f"Your Monthly Price: **${new_price:.2f}** (Regular: ${BASE_PRICE})")
            if st.session_state.stripe_cid:
                url, err = create_checkout_session(st.session_state.stripe_cid, discount_percent)
                if url: st.link_button("Subscribe Now", url)
            if st.button("Logout"): st.session_state.clear(); st.rerun()
            st.stop()

    df_full = run_query("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=:id", params={"id": user_id})
    u_data = df_full.iloc[0]
    logo, c_name, c_addr, terms = u_data['logo_data'], u_data['company_name'], u_data['company_address'], u_data['terms_conditions']
    if isinstance(logo, memoryview): logo = logo.tobytes()

    if trial_active:
        st.info(f"✨ Free Trial Active: {days_left} Days Remaining | Active Referrals: {active_referrals} (Current Discount: {discount_percent}%)")

    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Invoices", "Payments", "Settings"])
    
    if page == "Dashboard":
        col_t, col_l = st.columns([4, 1])
        with col_t:
            st.title(f"{c_name} - ProgressBill Pro" if c_name else "ProgressBill Pro")
            st.caption(f"Financial Overview for {c_name or 'My Firm'}")
        with col_l:
            if logo: st.image(logo, width=150)
        st.markdown("---")
        
        def get_scalar(q, p):
            res = run_query(q, p)
            return res.iloc[0, 0] if not res.empty and res.iloc[0, 0] is not None else 0.0

        t_contracts = get_scalar("SELECT SUM(quoted_price) FROM projects WHERE user_id=:id", {"id": user_id})
        t_invoiced = get_scalar("SELECT SUM(amount) FROM invoices WHERE user_id=:id", {"id": user_id})
        t_collected = get_scalar("SELECT SUM(amount) FROM payments WHERE user_id=:id", {"id": user_id})
        remaining_to_invoice = t_contracts - t_invoiced
        outstanding_ar = t_invoiced - t_collected
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Contracts", f"${t_contracts:,.2f}")
        m2.metric("Total Invoiced", f"${t_invoiced:,.2f}")
        m3.metric("Total Collected", f"${t_collected:,.2f}")
        
        m4, m5 = st.columns(2)
        m4.metric("Remaining to Invoice", f"${remaining_to_invoice:,.2f}")
        m5.metric("Outstanding AR (Unpaid)", f"${outstanding_ar:,.2f}", delta_color="inverse")
        
        # Dashboard PDF Export
        dash_metrics = {
            "Total Contracts": f"${t_contracts:,.2f}",
            "Total Invoiced": f"${t_invoiced:,.2f}",
            "Total Collected": f"${t_collected:,.2f}",
            "Remaining to Invoice": f"${remaining_to_invoice:,.2f}",
            "Outstanding AR": f"${outstanding_ar:,.2f}"
        }
        
        chart_data_pdf = {
            'Invoiced': t_invoiced,
            'Collected': t_collected,
            'Outstanding': outstanding_ar,
            'Remaining': remaining_to_invoice
        }
        
        pdf_bytes = generate_dashboard_pdf(dash_metrics, c_name or "My Firm", logo, chart_data_pdf)
        report_name = f"{c_name or 'Company'}_Executive_Report_{datetime.date.today()}.pdf"
        st.download_button("📂 Download Dashboard Report (PDF)", pdf_bytes, report_name, "application/pdf")
        
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Revenue Breakdown")
            chart_data = pd.DataFrame({'Category': ['Invoiced', 'Collected', 'Outstanding AR'], 'Amount': [t_invoiced, t_collected, outstanding_ar]})
            c = alt.Chart(chart_data).mark_bar().encode(x='Category', y='Amount', color=alt.Color('Category', scale=alt.Scale(scheme='tableau10'))).properties(height=300)
            st.altair_chart(c, use_container_width=True)
        with c2:
            st.markdown("##### Contract Progress")
            pie_data = pd.DataFrame({'Status': ['Invoiced', 'Remaining'], 'Value': [t_invoiced, remaining_to_invoice]})
            base = alt.Chart(pie_data).encode(theta=alt.Theta("Value", stack=True))
            pie = base.mark_arc(innerRadius=50).encode(color=alt.Color("Status", scale=alt.Scale(domain=['Invoiced', 'Remaining'], range=['#2B588D', '#DAA520'])), tooltip=["Status", "Value"]).properties(height=300)
            st.altair_chart(pie, use_container_width=True)

        st.markdown("---"); st.subheader("🔍 Project Deep-Dive")
        projs = run_query("SELECT id, name, client_name FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_id = int(projs[projs['name'] == p_choice]['id'].values[0])
            client_name = projs[projs['name'] == p_choice]['client_name'].values[0]
            
            p_row = run_query("SELECT quoted_price, start_date, duration, status FROM projects WHERE id=:id", {"id": p_id}).iloc[0]
            p_quoted, p_status = p_row['quoted_price'] or 0.0, p_row['status']
            
            df_inv = run_query("SELECT issue_date, invoice_num, amount, description FROM invoices WHERE project_id=:pid", {"pid": p_id})
            df_pay = run_query("SELECT payment_date, amount, notes FROM payments WHERE project_id=:pid", {"pid": p_id})
            
            ledger = []
            for _, r in df_inv.iterrows():
                ledger.append({'Date': r['issue_date'], 'Details': f"Invoice #{r['invoice_num']}", 'Charge': r['amount'], 'Payment': 0, 'Type': 'Inv'})
            for _, r in df_pay.iterrows():
                ledger.append({'Date': r['payment_date'], 'Details': f"Payment ({r['notes']})", 'Charge': 0, 'Payment': r['amount'], 'Type': 'Pay'})
            
            df_ledger = pd.DataFrame(ledger)
            
            if not df_ledger.empty:
                df_ledger['Date'] = pd.to_datetime(df_ledger['Date'])
                df_ledger = df_ledger.sort_values(by='Date').reset_index(drop=True)
                df_ledger['Balance'] = (df_ledger['Charge'] - df_ledger['Payment']).cumsum()
                df_ledger['Date'] = df_ledger['Date'].dt.date
                
                tot_bill = df_ledger['Charge'].sum()
                tot_paid = df_ledger['Payment'].sum()
                curr_bal = tot_bill - tot_paid
                
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric("Contract Value", f"${p_quoted:,.2f}")
                pc2.metric("Total Billed", f"${tot_bill:,.2f}")
                pc3.metric("Current Balance", f"${curr_bal:,.2f}", delta_color="inverse")
                
                # Statement PDF
                st.markdown("### Project Ledger")
                c_pdf, c_tbl = st.columns([1, 4])
                with c_pdf:
                    pdf_bytes = generate_statement_pdf(df_ledger, logo, {"name": c_name, "address": c_addr}, p_choice, client_name)
                    st.download_button("📄 Download Statement (PDF)", pdf_bytes, f"statement_{p_choice}.pdf", "application/pdf")
                
                st.dataframe(df_ledger[['Date', 'Details', 'Charge', 'Payment', 'Balance']].style.format("{:.2f}", subset=['Charge', 'Payment', 'Balance']), use_container_width=True)
                
                l1, l2 = st.columns(2)
                with l1:
                    st.markdown("##### Account Balance History")
                    line = alt.Chart(df_ledger).mark_line(point=True, color='#2B588D').encode(x='Date', y='Balance', tooltip=['Date', 'Balance']).properties(height=300)
                    st.altair_chart(line, use_container_width=True)
                with l2:
                    st.markdown("##### Billed vs Collected")
                    bar_df = pd.DataFrame({'Category': ['Billed', 'Collected'], 'Amount': [tot_bill, tot_paid]})
                    bar = alt.Chart(bar_df).mark_bar().encode(x='Category', y='Amount', color='Category').properties(height=300)
                    st.altair_chart(bar, use_container_width=True)
            else:
                st.info("No transactions recorded yet for this project.")
        else: st.info("No projects found.")

    elif page == "Projects":
        st.subheader("Manage Projects")
        with st.expander("Create New Project", expanded=False):
            with st.form("new_proj"):
                c1, c2 = st.columns(2)
                n = c1.text_input("Project Name"); c = c2.text_input("Client Name")
                # CHANGED TO TEXT INPUT FOR BETTER UX
                q_str = c1.text_input("Quoted Price ($)", placeholder="0.00")
                dur = c2.number_input("Duration (Days)", min_value=1)
                st.markdown("##### Addresses")
                ac1, ac2 = st.columns(2)
                with ac1: b_street = st.text_input("Billing Street"); b_city = st.text_input("Billing City"); b_state = st.text_input("Billing State"); b_zip = st.text_input("Billing Zip")
                with ac2: s_street = st.text_input("Site Street"); s_city = st.text_input("Site City"); s_state = st.text_input("Site State"); s_zip = st.text_input("Site Zip")
                st.markdown("##### Details")
                start_d = c1.date_input("Start Date"); po = c2.text_input("PO Number")
                status = c1.selectbox("Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"])
                is_tax_exempt = c2.checkbox("Tax Exempt?"); scope = st.text_area("Scope")
                submitted = st.form_submit_button("Create Project")
                if submitted:
                    # Clean the currency string before inserting
                    q = parse_currency(q_str)
                    
                    execute_statement("""
                        INSERT INTO projects (user_id, name, client_name, quoted_price, start_date, duration, billing_street, billing_city, billing_state, billing_zip, site_street, site_city, site_state, site_zip, is_tax_exempt, po_number, status, scope_of_work) 
                        VALUES (:uid, :n, :c, :q, :sd, :d, :bs, :bc, :bst, :bz, :ss, :sc, :sst, :sz, :ite, :po, :stat, :scope)
                    """, params={
                        "uid": user_id, "n": n, "c": c, "q": q, "sd": str(start_d), "d": dur, 
                        "bs": b_street, "bc": b_city, "bst": b_state, "bz": b_zip, 
                        "ss": s_street, "sc": s_city, "sst": s_state, "sz": s_zip, 
                        "ite": 1 if is_tax_exempt else 0, "po": po, "stat": status, "scope": scope
                    })
                    st.success("Project Saved"); st.rerun()
        
        st.markdown("### Project Management")
        projs = run_query("SELECT id, name, client_name, status, quoted_price FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            c_man_1, c_man_2 = st.columns([2, 2])
            with c_man_1:
                p_update = st.selectbox("Update Project", projs['name'], key="up_sel")
                new_stat = st.selectbox("New Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"], key="new_stat")
                if st.button("Update Status"):
                    pid = int(projs[projs['name'] == p_update]['id'].values[0])
                    execute_statement("UPDATE projects SET status=:s WHERE id=:id", {"s": new_stat, "id": pid})
                    st.success("Updated"); st.rerun()
            with c_man_2:
                p_del = st.selectbox("Delete Project", projs['name'], key="del_sel")
                if st.button("Delete", type="primary"):
                    pid = int(projs[projs['name'] == p_del]['id'].values[0])
                    execute_statement("DELETE FROM projects WHERE id=:id", {"id": pid})
                    execute_statement("DELETE FROM invoices WHERE project_id=:id", {"id": pid})
                    execute_statement("DELETE FROM payments WHERE project_id=:id", {"id": pid})
                    st.warning("Deleted"); st.rerun()
            st.dataframe(projs, use_container_width=True)
        else: st.info("No active projects.")

    elif page == "Invoices":
        st.subheader("Invoicing")
        projs = run_query("SELECT * FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            tax_label = "Tax ($)" + (" - [EXEMPT]" if row['is_tax_exempt'] else "")
            
            with st.form("inv", clear_on_submit=True):
                st.warning(f"Creating invoice for: **{row['name']}**")
                inv_date = st.date_input("Date", value=datetime.date.today())
                
                # CHANGED TO TEXT INPUTS
                a_str = st.text_input("Amount ($)", placeholder="0.00")
                t_str = st.text_input(tax_label, placeholder="0.00")
                d = st.text_area("Desc")
                
                verified = st.checkbox("I verify billing is correct")
                submitted = st.form_submit_button("Generate")
                if submitted:
                    if verified:
                        # Clean currency strings
                        a = parse_currency(a_str)
                        t = parse_currency(t_str)
                        
                        res_num = run_query("SELECT MAX(invoice_num) FROM invoices WHERE user_id=:id", {"id": user_id})
                        current_max = res_num.iloc[0, 0] if not res_num.empty and res_num.iloc[0, 0] is not None else 1000
                        num = current_max + 1
                        
                        p_info = {k: row[k] for k in ['name', 'client_name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'site_street', 'site_city', 'site_state', 'site_zip', 'po_number']}
                        pdf = generate_pdf_invoice({'number': num, 'amount': a+t, 'tax': t, 'date': str(inv_date), 'description': d}, logo, {'name': c_name, 'address': c_addr}, p_info, terms)
                        st.session_state.pdf = pdf
                        
                        # --- CAPTURE FILENAME FOR DOWNLOAD BUTTON ---
                        file_name = f"{row['client_name']}_Invoice#{num}_{inv_date}.pdf"
                        st.session_state.inv_filename = file_name
                        
                        execute_statement("""
                            INSERT INTO invoices (user_id, project_id, invoice_num, amount, issue_date, description, tax) 
                            VALUES (:uid, :pid, :num, :amt, :dt, :desc, :tax)
                        """, {"uid": user_id, "pid": int(row['id']), "num": int(num), "amt": a+t, "dt": str(inv_date), "desc": d, "tax": t})
                        st.success(f"Invoice #{num} Generated")
                    else: st.error("Please verify details.")
            if "pdf" in st.session_state:
                fname = st.session_state.get("inv_filename", "invoice.pdf")
                st.download_button("Download PDF", st.session_state.pdf, fname, "application/pdf")

    elif page == "Payments":
        st.subheader("Receive Payment")
        projs = run_query("SELECT * FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            with st.form("pay_form", clear_on_submit=True):
                st.warning(f"Logging payment for: **{row['name']}**")
                
                # CHANGED TO TEXT INPUT
                amt_str = st.text_input("Amount ($)", placeholder="0.00")
                
                pay_date = st.date_input("Date"); notes = st.text_input("Notes")
                verified_pay = st.checkbox("I verify payment details")
                submitted_pay = st.form_submit_button("Log Payment")
                if submitted_pay:
                    if verified_pay:
                        # Clean currency string
                        amt = parse_currency(amt_str)
                        
                        execute_statement("INSERT INTO payments (user_id, project_id, amount, payment_date, notes) VALUES (:uid, :pid, :amt, :dt, :n)", 
                                          {"uid": user_id, "pid": int(row['id']), "amt": amt, "dt": str(pay_date), "n": notes})
                        st.success("Logged")
                    else: st.error("Please verify details.")
            st.markdown("### History")
            hist = run_query("SELECT payment_date, amount, notes FROM payments WHERE project_id=:pid", {"pid": int(row['id'])})
            st.dataframe(hist)

    elif page == "Settings":
        st.header("Company Settings")
        st.markdown(f"""<div class="referral-box"><h3>🚀 Referral Program</h3><p>Share your code to earn <b>10% OFF</b> for every active user you refer! (10 Referrals = FREE)</p><h2>{my_code}</h2><p>Active Referrals: <b>{active_referrals}</b> | Current Discount: <b>{discount_percent}%</b></p></div><br>""", unsafe_allow_html=True)
        st.progress(min(discount_percent, 100) / 100)
        st.markdown("### Edit Profile")
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or ""); ca = st.text_area("Address", value=c_addr or ""); t_cond = st.text_area("Terms", value=terms or ""); l = st.file_uploader("Logo")
            submitted_set = st.form_submit_button("Save")
            if submitted_set:
                existing = run_query("SELECT id FROM users WHERE company_name=:cn AND id!=:uid", {"cn": cn, "uid": user_id})
                if not existing.empty and cn.strip() != "": st.error("⚠️ Company Name already registered.")
                else:
                    if l:
                        lb = l.read()
                        execute_statement("UPDATE users SET company_name=:cn, company_address=:ca, logo_data=:ld, terms_conditions=:tc WHERE id=:uid", {"cn": cn, "ca": ca, "ld": lb, "tc": t_cond, "uid": user_id})
                    else:
                        execute_statement("UPDATE users SET company_name=:cn, company_address=:ca, terms_conditions=:tc WHERE id=:uid", {"cn": cn, "ca": ca, "tc": t_cond, "uid": user_id})
                    st.success("Saved"); st.rerun()

    if st.sidebar.button("Logout"): st.session_state.clear(); st.rerun()