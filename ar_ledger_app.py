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
import altair as alt 
from fpdf import FPDF

# --- 1. CONFIGURATION & BRANDING ---
st.set_page_config(page_title="Balance & Build AR Ledger", layout="wide")

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
BASE_PRICE = 29.99 # Set your base monthly price here
BB_WATERMARK = "Powered by Balance & Build Consulting, LLC"
DB_FILE = "ar_ledger.db"
TERMS_URL = "https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf"

# --- 2. DATABASE ENGINE ---
def get_db_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

conn = get_db_connection()

def init_db():
    c = conn.cursor()
    # USERS: Added 'referred_by' to track the upstream referrer
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, email TEXT,
        logo_data BLOB, terms_conditions TEXT, company_name TEXT, company_address TEXT,
        company_phone TEXT, subscription_status TEXT DEFAULT 'Inactive', 
        created_at TEXT,
        stripe_customer_id TEXT, stripe_subscription_id TEXT,
        referral_code TEXT UNIQUE, referral_count INTEGER DEFAULT 0,
        referred_by TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, client_name TEXT,
        quoted_price REAL, start_date TEXT, duration INTEGER,
        billing_street TEXT, billing_city TEXT, billing_state TEXT, billing_zip TEXT,
        site_street TEXT, site_city TEXT, site_state TEXT, site_zip TEXT,
        is_tax_exempt INTEGER DEFAULT 0, po_number TEXT,
        status TEXT DEFAULT 'Bidding',
        scope_of_work TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        number INTEGER, amount REAL, date TEXT, description TEXT, tax REAL DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, project_id INTEGER,
        amount REAL, date TEXT, notes TEXT
    )''')
    conn.commit()

init_db()

# --- 3. HELPER FUNCTIONS ---
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def get_referral_stats(my_code):
    """Calculates active referrals and current discount."""
    if not my_code: return 0, 0
    # Count users referred by this code who are Active or in Trial
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=? AND subscription_status IN ('Active', 'Trial')", (my_code,))
    active_count = c.fetchone()[0]
    discount_percent = min(active_count * 10, 100) # Cap at 100%
    return active_count, discount_percent

class InvoicePDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 10, BB_WATERMARK, 0, 0, 'C')

def generate_pdf_invoice(inv_data, logo_data, company_info, project_info, terms):
    pdf = InvoicePDF()
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
    
    pdf.set_xy(120, 35)
    pdf.set_font("Arial", "B", 16); pdf.set_text_color(43, 88, 141)
    pdf.cell(0, 10, f"INVOICE #{inv_data['number']}", ln=1, align='R')
    pdf.set_font("Arial", "B", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, f"DATE: {inv_data['date']}", ln=1, align='R')
    if project_info.get('po_number'):
        pdf.cell(0, 5, f"PO #: {project_info['po_number']}", ln=1, align='R')

    pdf.set_xy(10, 60) 
    pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "BILL TO:", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, f"{project_info['client_name']}", ln=1)
    if project_info.get('billing_street'):
        pdf.cell(0, 5, f"{project_info['billing_street']}", ln=1)
        pdf.cell(0, 5, f"{project_info['billing_city']}, {project_info['billing_state']} {project_info['billing_zip']}", ln=1)
    
    right_x = 110; current_y = 60 
    pdf.set_xy(right_x, current_y)
    pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "PROJECT SITE:")
    current_y += 5
    pdf.set_xy(right_x, current_y)
    pdf.set_font("Arial", size=10); pdf.cell(0, 5, f"{project_info['name']}")
    if project_info.get('site_street'):
        current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, f"{project_info['site_street']}")
        current_y += 5; pdf.set_xy(right_x, current_y); pdf.cell(0, 5, f"{project_info['site_city']}, {project_info['site_state']} {project_info['site_zip']}")

    pdf.set_xy(10, 95) 
    pdf.set_font("Arial", "B", 10); pdf.cell(0, 5, "DESCRIPTION:", ln=1)
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

def create_checkout_session(customer_id, discount_percent):
    try:
        # In a real app, you would create a Stripe Coupon here dynamically based on discount_percent
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        if not prices.data: return None, "Price Not Found"
        
        session_args = {
            'customer': customer_id,
            'payment_method_types': ['card'],
            'line_items': [{'price': prices.data[0].id, 'quantity': 1}],
            'mode': 'subscription',
            'success_url': 'https://example.com/success',
            'cancel_url': 'https://example.com/cancel'
        }
        
        # NOTE: To fully enable coupon logic, you would pass 'discounts': [{'coupon': 'COUPON_ID'}] here.
        # For this MVP, we are calculating it in the UI.
        
        session = stripe.checkout.Session.create(**session_args)
        return session.url, None
    except Exception as e: return None, str(e)

def create_stripe_customer(email, name):
    try:
        return stripe.Customer.create(email=email, name=name).id
    except: return None

# --- 4. AUTHENTICATION (MANUAL) ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = None

# --- 5. LOGIC FLOW ---
if st.session_state.user_id is None:
    if os.path.exists("bb_logo.png"): st.image("bb_logo.png", width=200)
    else: st.title("Balance & Build Consulting")

    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                rec = conn.execute("SELECT id, password, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE username=?", (u,)).fetchone()
                if rec:
                    if check_password(p, rec[1]):
                        st.session_state.user_id = rec[0]
                        st.session_state.sub_status = rec[2]
                        st.session_state.stripe_cid = rec[3]
                        st.session_state.created_at = rec[4]
                        st.session_state.my_ref_code = rec[5]
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
            
            if st.form_submit_button("Create Account"):
                if not terms_agreed: st.error("You must agree to the Terms and Conditions.")
                elif u and p and e:
                    try:
                        h_p = hash_password(p); cid = create_stripe_customer(e, u)
                        my_ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        today_str = str(datetime.date.today())
                        
                        # Store 'ref_input' into 'referred_by'
                        conn.execute("INSERT INTO users (username, password, email, stripe_customer_id, referral_code, created_at, subscription_status, referred_by) VALUES (?,?,?,?,?,?,?,?)", 
                                     (u, h_p, e, cid, my_ref_code, today_str, 'Trial', ref_input))
                        conn.commit(); st.success("Account Created! Please switch to Login tab.")
                    except sqlite3.IntegrityError: st.error("Username already taken.")
                    except Exception as err: st.error(f"Error: {err}")
                else: st.warning("Please fill all fields")

else:
    user_id = st.session_state.user_id
    
    # --- CALCULATE DISCOUNT & TRIAL ---
    status = st.session_state.sub_status
    created_at_str = st.session_state.get('created_at')
    my_code = st.session_state.get('my_ref_code')
    
    active_referrals, discount_percent = get_referral_stats(my_code)
    
    # Check Trial
    days_left = 0
    trial_active = False
    if status == 'Trial' and created_at_str:
        try:
            start_date = datetime.datetime.strptime(created_at_str, '%Y-%m-%d').date()
            days_elapsed = (datetime.date.today() - start_date).days
            days_left = 30 - days_elapsed
            if days_left > 0: trial_active = True
        except: pass

    # If Locked Out (Trial Over & Not Active)
    if status != 'Active' and not trial_active:
        if discount_percent >= 100:
            st.balloons()
            st.success("🎉 You have earned FREE ACCESS with 10+ Referrals!")
            if st.button("Activate Free Lifetime Access"):
                conn.execute("UPDATE users SET subscription_status='Active' WHERE id=?", (user_id,))
                conn.commit(); st.session_state.sub_status = 'Active'; st.rerun()
        else:
            st.warning(f"⚠️ Trial Expired. You have {active_referrals} Active Referrals ({discount_percent}% Discount).")
            new_price = BASE_PRICE * (1 - (discount_percent/100))
            st.info(f"Your Monthly Price: **${new_price:.2f}** (Regular: ${BASE_PRICE})")
            
            if st.session_state.stripe_cid:
                url, err = create_checkout_session(st.session_state.stripe_cid, discount_percent)
                if url: st.link_button("Subscribe Now", url)
            
            if st.button("Logout"): st.session_state.clear(); st.rerun()
            st.stop()

    # --- MAIN APP UI ---
    u_data = conn.execute("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=?", (user_id,)).fetchone()
    if u_data is None: st.warning("Session expired."); st.session_state.clear(); st.rerun(); st.stop()
    logo, c_name, c_addr, terms = u_data
    
    # Trial Banner
    if trial_active:
        st.info(f"✨ Free Trial Active: {days_left} Days Remaining | Active Referrals: {active_referrals} (Current Discount: {discount_percent}%)")

    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Invoices", "Payments", "Settings"])
    
    if page == "Dashboard":
        col_t, col_l = st.columns([4, 1])
        with col_t:
            display_title = f"{c_name} AR Ledger" if c_name else "Balance & Build AR Ledger"
            st.title(display_title); st.caption(f"Financial Overview for {c_name or 'My Firm'}")
        with col_l:
            if logo: st.image(logo, width=150)
        st.markdown("---")
        
        st.subheader("🏢 Firm-Wide Performance")
        t_contracts = conn.execute("SELECT SUM(quoted_price) FROM projects WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        t_invoiced = conn.execute("SELECT SUM(amount) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        t_collected = conn.execute("SELECT SUM(amount) FROM payments WHERE user_id=?", (user_id,)).fetchone()[0] or 0.0
        remaining_to_invoice = t_contracts - t_invoiced
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Contracts", f"${t_contracts:,.2f}"); m2.metric("Total Invoiced", f"${t_invoiced:,.2f}")
        m3.metric("Total Collected", f"${t_collected:,.2f}"); m4.metric("Remaining to Invoice", f"${remaining_to_invoice:,.2f}")
        
        st.markdown("<br>", unsafe_allow_html=True); c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Revenue Breakdown")
            chart_data = pd.DataFrame({'Category': ['Invoiced', 'Collected', 'Outstanding AR'], 'Amount': [t_invoiced, t_collected, t_invoiced - t_collected]})
            c = alt.Chart(chart_data).mark_bar().encode(x='Category', y='Amount', color=alt.Color('Category', scale=alt.Scale(scheme='tableau10'))).properties(height=300)
            st.altair_chart(c, use_container_width=True)
        with c2:
            st.markdown("##### Contract Progress")
            pie_data = pd.DataFrame({'Status': ['Invoiced', 'Remaining'], 'Value': [t_invoiced, remaining_to_invoice]})
            base = alt.Chart(pie_data).encode(theta=alt.Theta("Value", stack=True))
            pie = base.mark_arc(innerRadius=50).encode(color=alt.Color("Status", scale=alt.Scale(domain=['Invoiced', 'Remaining'], range=['#2B588D', '#DAA520'])), tooltip=["Status", "Value"]).properties(height=300)
            st.altair_chart(pie, use_container_width=True)

        st.markdown("---"); st.subheader("🔍 Project Deep-Dive")
        projs = pd.read_sql_query("SELECT id, name FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_id = projs[projs['name'] == p_choice]['id'].values[0]
            p_row = conn.execute("SELECT quoted_price, start_date, duration, status FROM projects WHERE id=?", (int(p_id),)).fetchone()
            p_quoted, p_start, p_duration, p_status = p_row if p_row else (0.0, "", 0, "")
            p_inv = conn.execute("SELECT SUM(amount) FROM invoices WHERE project_id=?", (int(p_id),)).fetchone()[0] or 0.0
            p_col = conn.execute("SELECT SUM(amount) FROM payments WHERE project_id=?", (int(p_id),)).fetchone()[0] or 0.0
            st.caption(f"Status: **{p_status}**")
            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric(f"Contract", f"${p_quoted:,.2f}"); pm2.metric("Invoiced", f"${p_inv:,.2f}")
            pm3.metric("Collected", f"${p_col:,.2f}"); pm4.metric("Remaining", f"${p_quoted - p_inv:,.2f}")
            try:
                start_dt = datetime.datetime.strptime(p_start, '%Y-%m-%d').date(); end_dt = start_dt + datetime.timedelta(days=p_duration)
                timeline_chart = alt.Chart(pd.DataFrame([{'Task': 'Project Duration', 'Start': str(start_dt), 'End': str(end_dt), 'Project': p_choice}])).mark_bar(size=20, color='#2B588D').encode(x='Start:T', x2='End:T', y=alt.Y('Project', axis=None), tooltip=['Task', 'Start', 'End']).properties(height=100)
                st.altair_chart(timeline_chart, use_container_width=True)
            except: pass
        else: st.info("No projects found.")

    elif page == "Projects":
        st.subheader("Manage Projects")
        with st.expander("Create New Project", expanded=False):
            with st.form("new_proj"):
                c1, c2 = st.columns(2)
                n = c1.text_input("Project Name"); c = c2.text_input("Client Name")
                q = c1.number_input("Quoted Price ($)", min_value=0.0); dur = c2.number_input("Duration (Days)", min_value=1)
                st.markdown("##### Addresses")
                ac1, ac2 = st.columns(2)
                with ac1: b_street = st.text_input("Billing Street"); b_city = st.text_input("Billing City"); b_state = st.text_input("Billing State"); b_zip = st.text_input("Billing Zip")
                with ac2: s_street = st.text_input("Site Street"); s_city = st.text_input("Site City"); s_state = st.text_input("Site State"); s_zip = st.text_input("Site Zip")
                st.markdown("##### Details")
                start_d = c1.date_input("Start Date"); po = c2.text_input("PO Number")
                status = c1.selectbox("Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"])
                is_tax_exempt = c2.checkbox("Tax Exempt?"); scope = st.text_area("Scope")
                if st.form_submit_button("Create Project"):
                    conn.execute("INSERT INTO projects (user_id, name, client_name, quoted_price, start_date, duration, billing_street, billing_city, billing_state, billing_zip, site_street, site_city, site_state, site_zip, is_tax_exempt, po_number, status, scope_of_work) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (user_id, n, c, q, str(start_d), dur, b_street, b_city, b_state, b_zip, s_street, s_city, s_state, s_zip, 1 if is_tax_exempt else 0, po, status, scope))
                    conn.commit(); st.success("Project Saved"); st.rerun()

        st.markdown("### Project Management")
        projs = pd.read_sql_query("SELECT id, name, client_name, status, quoted_price FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            c_man_1, c_man_2 = st.columns([2, 2])
            with c_man_1:
                p_update = st.selectbox("Update Project", projs['name'], key="up_sel")
                new_stat = st.selectbox("New Status", ["Bidding", "Pre-Construction", "Course of Construction", "Warranty", "Post-Construction"], key="new_stat")
                if st.button("Update Status"):
                    pid = projs[projs['name'] == p_update]['id'].values[0]
                    conn.execute("UPDATE projects SET status=? WHERE id=?", (new_stat, int(pid))); conn.commit(); st.success("Updated"); st.rerun()
            with c_man_2:
                p_del = st.selectbox("Delete Project", projs['name'], key="del_sel")
                if st.button("Delete", type="primary"):
                    pid = projs[projs['name'] == p_del]['id'].values[0]
                    conn.execute("DELETE FROM projects WHERE id=?", (int(pid),)); conn.execute("DELETE FROM invoices WHERE project_id=?", (int(pid),)); conn.execute("DELETE FROM payments WHERE project_id=?", (int(pid),)); conn.commit(); st.warning("Deleted"); st.rerun()
            st.dataframe(projs, use_container_width=True)
        else: st.info("No active projects.")

    elif page == "Invoices":
        st.subheader("Invoicing")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            tax_label = "Tax ($)" + (" - [EXEMPT]" if row['is_tax_exempt'] else "")
            with st.form("inv", clear_on_submit=True):
                st.warning(f"Creating invoice for: **{row['name']}**")
                inv_date = st.date_input("Date", value=datetime.date.today()); a = st.number_input("Amount"); t = st.number_input(tax_label); d = st.text_area("Desc")
                if st.checkbox("I verify billing is correct") and st.form_submit_button("Generate"):
                    num = (conn.execute("SELECT MAX(number) FROM invoices WHERE user_id=?", (user_id,)).fetchone()[0] or 1000) + 1
                    p_info = {k: row[k] for k in ['name', 'client_name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'site_street', 'site_city', 'site_state', 'site_zip', 'po_number']}
                    pdf = generate_pdf_invoice({'number': num, 'amount': a+t, 'tax': t, 'date': str(inv_date), 'description': d}, logo, {'name': c_name, 'address': c_addr}, p_info, terms)
                    st.session_state.pdf = pdf
                    conn.execute("INSERT INTO invoices (user_id, project_id, number, amount, date, description, tax) VALUES (?,?,?,?,?,?,?)", (user_id, int(row['id']), num, a+t, str(inv_date), d, t)); conn.commit(); st.success(f"Invoice #{num} Generated")
            if "pdf" in st.session_state: st.download_button("Download PDF", st.session_state.pdf, "inv.pdf")

    elif page == "Payments":
        st.subheader("Receive Payment")
        projs = pd.read_sql_query("SELECT * FROM projects WHERE user_id=?", conn, params=(user_id,))
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            with st.form("pay_form", clear_on_submit=True):
                st.warning(f"Logging payment for: **{row['name']}**")
                amt = st.number_input("Amount"); pay_date = st.date_input("Date"); notes = st.text_input("Notes")
                if st.checkbox("I verify payment details") and st.form_submit_button("Log Payment"):
                    conn.execute("INSERT INTO payments (user_id, project_id, amount, date, notes) VALUES (?,?,?,?,?)", (user_id, int(row['id']), amt, str(pay_date), notes)); conn.commit(); st.success("Logged")
            st.markdown("### History")
            st.dataframe(pd.read_sql_query("SELECT date, amount, notes FROM payments WHERE project_id=?", conn, params=(int(row['id']),)))

    elif page == "Settings":
        st.header("Company Settings")
        
        # --- REFERRAL HUB ---
        st.markdown(f"""
        <div class="referral-box">
            <h3>🚀 Referral Program</h3>
            <p>Share your code to earn <b>10% OFF</b> for every active user you refer! (10 Referrals = FREE)</p>
            <h2>{my_code}</h2>
            <p>Active Referrals: <b>{active_referrals}</b> | Current Discount: <b>{discount_percent}%</b></p>
        </div>
        <br>
        """, unsafe_allow_html=True)
        st.progress(min(discount_percent, 100) / 100)
        
        st.markdown("### Edit Profile")
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or ""); ca = st.text_area("Address", value=c_addr or ""); t_cond = st.text_area("Terms", value=terms or ""); l = st.file_uploader("Logo")
            if st.form_submit_button("Save"):
                lb = l.read() if l else logo
                conn.execute("UPDATE users SET company_name=?, company_address=?, logo_data=?, terms_conditions=? WHERE id=?", (cn, ca, lb, t_cond, user_id)); conn.commit(); st.success("Saved"); st.rerun()

    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()