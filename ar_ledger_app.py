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
from fpdf import FPDF
from sqlalchemy import text, exc

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
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
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
BB_WATERMARK = "Powered by Balance & Build Consulting, LLC"
TERMS_URL = "https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf"

# --- 2. DATABASE ENGINE (POSTGRESQL + RETRY LOGIC) ---
conn = st.connection("supabase", type="sql")

def run_query(query, params=None):
    """Helper to run queries safely with parameters (Returns DataFrame)"""
    return conn.query(query, params=params, ttl=0)

def execute_statement(query, params=None):
    """
    Executes a write operation with automatic retry logic.
    """
    try:
        with conn.session as s:
            s.execute(text(query), params)
            s.commit()
    except exc.OperationalError:
        # DB Connection died. Wait, reset, and retry once.
        time.sleep(1)
        st.cache_resource.clear() 
        try:
            with conn.session as s:
                s.execute(text(query), params)
                s.commit()
        except Exception as e:
            with conn.session as s:
                s.rollback()
            raise e
    except Exception as e:
        with conn.session as s:
            s.rollback()
        raise e

def init_db():
    # Initialize Tables safely. Removed try/except so we can see if creation fails.
    with conn.session as s:
        s.execute(text('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT,
            logo_data BYTEA, terms_conditions TEXT, company_name TEXT, company_address TEXT, 
            company_phone TEXT, subscription_status TEXT DEFAULT 'Inactive', created_at TEXT,
            stripe_customer_id TEXT, stripe_subscription_id TEXT, referral_code TEXT UNIQUE, 
            referral_count INTEGER DEFAULT 0, referred_by TEXT
        )'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY, user_id INTEGER, name TEXT, client_name TEXT,
            quoted_price REAL, start_date TEXT, duration INTEGER,
            billing_street TEXT, billing_city TEXT, billing_state TEXT, billing_zip TEXT,
            site_street TEXT, site_city TEXT, site_state TEXT, site_zip TEXT,
            is_tax_exempt INTEGER DEFAULT 0, po_number TEXT, status TEXT DEFAULT 'Bidding', scope_of_work TEXT
        )'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY, user_id INTEGER, project_id INTEGER, number INTEGER, 
            amount REAL, date TEXT, description TEXT, tax REAL DEFAULT 0
        )'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY, user_id INTEGER, project_id INTEGER, amount REAL, 
            date TEXT, notes TEXT
        )'''))
        s.commit()

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
                if isinstance(logo_data, memoryview): tmp.write(logo_data.tobytes())
                else: tmp.write(logo_data)
                tmp_path = tmp.name
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
    else: st.title("Balance & Build Consulting")

    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                with conn.session as s:
                    res = s.execute(text("SELECT id, password, subscription_status, stripe_customer_id, created_at, referral_code FROM users WHERE username=:u"), {"u": u}).fetchone()
                    if res:
                        if check_password(p, res[1]):
                            st.session_state.user_id = int(res[0]); st.session_state.sub_status = res[2]
                            st.session_state.stripe_cid = res[3]; st.session_state.created_at = res[4]
                            st.session_state.my_ref_code = res[5]
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
                        check = run_query("SELECT id FROM users WHERE username=:u", params={"u": u})
                        if not check.empty: st.error("Username already taken.")
                        else:
                            h_p = hash_password(p); cid = create_stripe_customer(e, u)
                            my_ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                            today_str = str(datetime.date.today())
                            if ref_input:
                                execute_statement("UPDATE users SET referral_count = referral_count + 1 WHERE referral_code=:c", params={"c": ref_input})
                            
                            # Using quoted identifiers just in case
                            execute_statement("""
                                INSERT INTO users ("username", "password", "email", "stripe_customer_id", "referral_code", "created_at", "subscription_status", "referred_by") 
                                VALUES (:u, :p, :e, :cid, :rc, :ca, 'Trial', :rb)
                            """, params={"u": u, "p": h_p, "e": e, "cid": cid, "rc": my_ref_code, "ca": today_str, "rb": ref_input})
                            st.success("Account Created! Please switch to Login tab.")
                    except Exception as err: st.error(f"Error: {err}")
                else: st.warning("Please fill all fields")

else:
    user_id = st.session_state.user_id
    with conn.session as s:
        res = s.execute(text("SELECT subscription_status, created_at, referral_code FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        if not res: st.session_state.clear(); st.rerun()
        status, created_at_str, my_code = res[0], res[1], res[2]
    
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

    with conn.session as s:
        res_full = s.execute(text("SELECT logo_data, company_name, company_address, terms_conditions FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        logo, c_name, c_addr, terms = res_full[0], res_full[1], res_full[2], res_full[3]
        if isinstance(logo, memoryview): logo = logo.tobytes()

    if trial_active:
        st.info(f"✨ Free Trial Active: {days_left} Days Remaining | Active Referrals: {active_referrals} (Current Discount: {discount_percent}%)")

    page = st.sidebar.radio("Navigate", ["Dashboard", "Projects", "Invoices", "Payments", "Settings"])
    
    if page == "Dashboard":
        col_t, col_l = st.columns([4, 1])
        with col_t:
            st.title(f"{c_name} AR Ledger" if c_name else "Balance & Build AR Ledger")
            st.caption(f"Financial Overview for {c_name or 'My Firm'}")
        with col_l:
            if logo: st.image(logo, width=150)
        st.markdown("---")
        
        # Helper for scalar
        def get_scalar(q, p):
            res = run_query(q, p)
            return res.iloc[0, 0] if not res.empty and res.iloc[0, 0] is not None else 0.0

        t_contracts = get_scalar("SELECT SUM(quoted_price) FROM projects WHERE user_id=:id", {"id": user_id})
        t_invoiced = get_scalar("SELECT SUM(amount) FROM invoices WHERE user_id=:id", {"id": user_id})
        t_collected = get_scalar("SELECT SUM(amount) FROM payments WHERE user_id=:id", {"id": user_id})
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
        projs = run_query("SELECT id, name FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p_choice = st.selectbox("Select Project", projs['name'])
            p_id = int(projs[projs['name'] == p_choice]['id'].values[0])
            
            p_row = run_query("SELECT quoted_price, start_date, duration, status FROM projects WHERE id=:id", {"id": p_id}).iloc[0]
            p_quoted, p_status = p_row['quoted_price'] or 0.0, p_row['status']
            
            # --- LEDGER LOGIC ---
            df_inv = run_query("SELECT date, number, amount, description FROM invoices WHERE project_id=:pid", {"pid": p_id})
            df_pay = run_query("SELECT date, amount, notes FROM payments WHERE project_id=:pid", {"pid": p_id})
            
            ledger_items = []
            for _, r in df_inv.iterrows():
                ledger_items.append({'Date': r['date'], 'Description': f"Invoice #{r['number']} - {r['description']}", 'Debit': r['amount'], 'Credit': 0, 'Type': 'Invoice'})
            for _, r in df_pay.iterrows():
                ledger_items.append({'Date': r['date'], 'Description': f"Payment - {r['notes']}", 'Debit': 0, 'Credit': r['amount'], 'Type': 'Payment'})
            
            df_ledger = pd.DataFrame(ledger_items)
            
            if not df_ledger.empty:
                df_ledger['Date'] = pd.to_datetime(df_ledger['Date'])
                df_ledger = df_ledger.sort_values(by='Date').reset_index(drop=True)
                df_ledger['Balance'] = (df_ledger['Debit'] - df_ledger['Credit']).cumsum()
                df_ledger['Date'] = df_ledger['Date'].dt.date
                
                total_inv = df_ledger['Debit'].sum()
                total_pay = df_ledger['Credit'].sum()
                current_bal = total_inv - total_pay
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Contract Value", f"${p_quoted:,.2f}")
                col2.metric("Total Billed", f"${total_inv:,.2f}")
                col3.metric("Current Balance (AR)", f"${current_bal:,.2f}", delta_color="inverse")
                
                st.markdown("### Project Ledger")
                st.dataframe(df_ledger, use_container_width=True)
                
                l1, l2 = st.columns(2)
                with l1:
                    st.markdown("##### Financial Trajectory (Running Balance)")
                    line = alt.Chart(df_ledger).mark_line(point=True).encode(x='Date', y='Balance', tooltip=['Date', 'Balance', 'Description']).properties(height=300)
                    st.altair_chart(line, use_container_width=True)
                with l2:
                    st.markdown("##### Billed vs Collected")
                    bar_data = pd.DataFrame({'Type': ['Billed', 'Collected'], 'Amount': [total_inv, total_pay]})
                    bar = alt.Chart(bar_data).mark_bar().encode(x='Type', y='Amount', color='Type', tooltip=['Type', 'Amount']).properties(height=300)
                    st.altair_chart(bar, use_container_width=True)
            else:
                st.info("No transactions yet for this project.")

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
                    execute_statement("""
                        INSERT INTO projects ("user_id", "name", "client_name", "quoted_price", "start_date", "duration", "billing_street", "billing_city", "billing_state", "billing_zip", "site_street", "site_city", "site_state", "site_zip", "is_tax_exempt", "po_number", "status", "scope_of_work") 
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
                inv_date = st.date_input("Date", value=datetime.date.today()); a = st.number_input("Amount"); t = st.number_input(tax_label); d = st.text_area("Desc")
                verified = st.checkbox("I verify billing is correct")
                submitted = st.form_submit_button("Generate")
                
                if submitted:
                    if verified:
                        res_num = run_query("SELECT MAX(number) FROM invoices WHERE user_id=:id", {"id": user_id})
                        current_max = res_num.iloc[0, 0] if not res_num.empty and res_num.iloc[0, 0] is not None else 1000
                        num = current_max + 1
                        
                        p_info = {k: row[k] for k in ['name', 'client_name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'site_street', 'site_city', 'site_state', 'site_zip', 'po_number']}
                        pdf = generate_pdf_invoice({'number': num, 'amount': a+t, 'tax': t, 'date': str(inv_date), 'description': d}, logo, {'name': c_name, 'address': c_addr}, p_info, terms)
                        st.session_state.pdf = pdf
                        
                        # --- FIX: Using Quoted Identifiers to prevent 'ProgrammingError' ---
                        execute_statement("""
                            INSERT INTO invoices ("user_id", "project_id", "number", "amount", "date", "description", "tax") 
                            VALUES (:uid, :pid, :num, :amt, :dt, :desc, :tax)
                        """, {"uid": user_id, "pid": int(row['id']), "num": num, "amt": a+t, "dt": str(inv_date), "desc": d, "tax": t})
                        st.success(f"Invoice #{num} Generated")
                    else: st.error("Please verify details.")
            if "pdf" in st.session_state: st.download_button("Download PDF", st.session_state.pdf, "inv.pdf")

    elif page == "Payments":
        st.subheader("Receive Payment")
        projs = run_query("SELECT * FROM projects WHERE user_id=:id", {"id": user_id})
        if not projs.empty:
            p = st.selectbox("Project", projs['name'])
            row = projs[projs['name']==p].iloc[0]
            with st.form("pay_form", clear_on_submit=True):
                st.warning(f"Logging payment for: **{row['name']}**")
                amt = st.number_input("Amount"); pay_date = st.date_input("Date"); notes = st.text_input("Notes")
                verified_pay = st.checkbox("I verify payment details")
                submitted_pay = st.form_submit_button("Log Payment")
                if submitted_pay:
                    if verified_pay:
                        execute_statement("""
                            INSERT INTO payments ("user_id", "project_id", "amount", "date", "notes") 
                            VALUES (:uid, :pid, :amt, :dt, :n)
                        """, {"uid": user_id, "pid": int(row['id']), "amt": amt, "dt": str(pay_date), "n": notes})
                        st.success("Logged")
                    else: st.error("Please verify details.")
            st.markdown("### History")
            hist = run_query("SELECT date, amount, notes FROM payments WHERE project_id=:pid", {"pid": int(row['id'])})
            st.dataframe(hist)

    elif page == "Settings":
        st.header("Company Settings")
        st.markdown(f"""<div class="referral-box"><h3>🚀 Referral Program</h3><p>Share your code to earn <b>10% OFF</b> for every active user you refer! (10 Referrals = FREE)</p><h2>{my_code}</h2><p>Active Referrals: <b>{active_referrals}</b> | Current Discount: <b>{discount_percent}%</b></p></div><br>""", unsafe_allow_html=True)
        st.progress(min(discount_percent, 100) / 100)
        st.markdown("### Edit Profile")
        with st.form("set"):
            cn = st.text_input("Company Name", value=c_name or ""); ca = st.text_area("Address", value=c_addr or ""); t_cond = st.text_area("Terms", value=terms or ""); l = st.file_uploader("Logo")
            if st.form_submit_button("Save"):
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