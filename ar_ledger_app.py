import streamlit as st
import pandas as pd
import sqlite3
import datetime
import smtplib
import random
import string
import stripe # Make sure to pip install stripe
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
# Check for secrets.toml keys first (used on Streamlit Cloud)
if "STRIPE_SECRET_KEY" in st.secrets:
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    STRIPE_PUBLISHABLE_KEY = st.secrets["STRIPE_PUBLISHABLE_KEY"]
    # We must also set the OS Environment variable for compatibility with some libraries
    # although Stripe usually reads stripe.api_key directly.
    os.environ['STRIPE_SECRET_KEY'] = st.secrets["STRIPE_SECRET_KEY"]
else:
    # Fallback for local testing if running outside Streamlit Cloud
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_51SNdNlC20flbf1hAK2LiwwJyfC4LdDiOdd8qMcM6xd3cWqENcvkIaUkiHrb0I0wLoNHW0KpGFDSU75TVojacWAMo00eyGw6dfh")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "pk_test_51SNdNlC20flbf1hAp0FoQLTppgIGuXzGEIWavR41ib3qHhlks5dpuoNV7gMnR5haNees5MPawAlhDKEyWHGWfI4B00ZGgwZmxi")

STRIPE_PRICE_LOOKUP_KEY = "standard_monthly" 

# ... rest of the code is unchanged

# Branding
BB_WATERMARK = "Powered by Balance & Build Consulting, LLC"
BB_LOGO_PATH = "bb_logo.png" 
DB_FILE = "ar_ledger.db"
USER_LOGOS_DIR = "user_logos"

if not os.path.exists(USER_LOGOS_DIR):
    os.makedirs(USER_LOGOS_DIR)

# --- DATABASE CONNECTION ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

conn = get_db_connection()

# --- DATABASE TABLES (FINAL PRODUCTION SCHEMA) ---
def init_db():
    c = conn.cursor()
    
    # USERS: Includes Stripe and Referral fields
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT,
        logo_data BLOB,
        terms_conditions TEXT,
        company_name TEXT,
        company_address TEXT,
        company_phone TEXT,
        company_website TEXT,
        tax_id TEXT,
        default_payment_instructions TEXT,
        subscription_status TEXT DEFAULT 'Inactive', -- Default is Inactive until they pay
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        referral_code TEXT UNIQUE,
        referred_by TEXT,
        referral_count INTEGER DEFAULT 0,
        accepted_terms BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        client_name TEXT,
        quoted_price REAL,
        start_date DATE,
        duration INTEGER,
        address TEXT,
        priority INTEGER,
        status TEXT DEFAULT 'Active',
        description TEXT,
        po_number TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        project_id INTEGER,
        name TEXT,
        email TEXT,
        phone TEXT,
        title TEXT,
        billing_address TEXT,
        is_primary BOOLEAN DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        project_id INTEGER,
        number INTEGER,
        amount REAL,
        date DATE,
        due_date DATE,
        description TEXT,
        tax REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        status TEXT DEFAULT 'Sent',
        payment_terms TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        project_id INTEGER,
        amount REAL,
        date DATE,
        form TEXT,
        check_number TEXT,
        notes TEXT,
        attachment_path TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        timestamp DATETIME
    )''')
    conn.commit()

init_db()

# --- HELPER FUNCTIONS ---

def generate_referral_code():
    """Generates a random 8-character string for referrals."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def hash_password(password):
    return Hasher.hash(password)

def send_email(to_email, subject, body):
    # Mock email function
    print(f"--- EMAIL SENT ---\nTo: {to_email}\nSubject: {subject}\nBody: {body}\n--------------------")
    st.toast(f"Email sent to {to_email}")

def generate_pdf_invoice(invoice_data, user_logo_data, company_info, terms, theme='default'):
    pdf = FPDF()
    pdf.add_page()
    # ... (content remains the same until Header section)

    pdf.set_text_color(0, 0, 0)
    
    # Header: LOGO DISPLAY CHANGE
    if user_logo_data:
        # Save the binary data to a temporary file, as FPDF needs a file path
        temp_logo_path = f"temp_logo_{random.randint(0, 99999)}.png"
        try:
            with open(temp_logo_path, "wb") as f:
                f.write(user_logo_data)
            pdf.image(temp_logo_path, 10, 15, 33) 
        except Exception as e:
            print(f"PDF Image Error: {e}")
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_logo_path):
                os.remove(temp_logo_path)
            
    pdf.set_xy(120, 15)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 5, company_info.get('name', 'My Company'), ln=1, align='R')
    
    pdf.set_font("Arial", size=10)
    if company_info.get('address'):
        pdf.set_x(120)
        pdf.cell(0, 5, company_info['address'], ln=1, align='R')
    if company_info.get('phone'):
        pdf.set_x(120)
        pdf.cell(0, 5, f"Tel: {company_info['phone']}", ln=1, align='R')
    if company_info.get('email'):
        pdf.set_x(120)
        pdf.cell(0, 5, company_info['email'], ln=1, align='R')

    pdf.ln(30)

    if theme == 'blue':
        pdf.set_text_color(0, 0, 150)
    
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Invoice #{invoice_data['number']}", ln=1)
    
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Date: {invoice_data['date']}", ln=1)
    pdf.cell(0, 10, f"Amount: ${invoice_data['amount']:,.2f}", ln=1)
    pdf.cell(0, 10, f"Tax: ${invoice_data['tax']:,.2f}", ln=1)
    pdf.cell(0, 10, f"Discount: ${invoice_data['discount']:,.2f}", ln=1)
    
    pdf.ln(10)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Description", ln=1)
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, invoice_data['description'])
    
    pdf.ln(20)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 10, "Terms & Conditions", ln=1)
    pdf.set_font("Arial", "I", 9)
    pdf.multi_cell(0, 5, terms)
    
    pdf_output = io.BytesIO()
    pdf_output.write(pdf.output(dest='S').encode('latin1'))
    pdf_output.seek(0)
    return pdf_output

def get_user_data(user_id, table, extra_where=""):
    try:
        query = f"SELECT * FROM {table} WHERE user_id = ? {extra_where}"
        df = pd.read_sql_query(query, conn, params=(user_id,), parse_dates=['date', 'start_date', 'timestamp'])
        return df
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

def log_audit(user_id, action):
    conn.execute("INSERT INTO audit_logs (user_id, action, timestamp) VALUES (?, ?, ?)",
                   (user_id, action, datetime.datetime.now()))
    conn.commit()

def send_reminders(user_id):
    if 'reminders_sent' not in st.session_state:
        invoices = get_user_data(user_id, "invoices")
        if not invoices.empty:
            for _, inv in invoices.iterrows():
                if pd.notnull(inv['date']):
                    inv_date = inv['date'].date() if isinstance(inv['date'], pd.Timestamp) else inv['date']
                    if (datetime.date.today() - inv_date).days > 30:
                        send_email("user@email.com", "Overdue Invoice", f"Invoice #{inv['number']} is overdue.")
        st.session_state['reminders_sent'] = True

def load_credentials():
    c = conn.cursor()
    c.execute("SELECT username, password, email, subscription_status FROM users")
    users = c.fetchall()
    
    credentials = {'usernames': {}}
    for user in users:
        username, hashed_pw, email, status = user
        credentials['usernames'][username] = {
            'name': username, 
            'password': hashed_pw, 
            'email': email
        }
    return credentials

# --- STRIPE LOGIC ---

def create_stripe_customer(email, name):
    try:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            description="AR Ledger App User"
        )
        return customer.id
    except Exception as e:
        st.error(f"Stripe Error: {e}")
        return None

def create_checkout_session(customer_id):
    try:
        # Fetch the Price ID using the Lookup Key "standard_monthly"
        prices = stripe.Price.list(lookup_keys=[STRIPE_PRICE_LOOKUP_KEY], limit=1)
        if not prices.data:
            return None, "Price Lookup Key not found in Stripe. Please check your Stripe Dashboard."
        
        price_id = prices.data[0].id
        
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            subscription_data={
                'trial_period_days': 30, # 30 Day Free Trial
            },
            # --- UPDATED URLS ---
            success_url='https://ar-ledger-app.streamlit.app/?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://ar-ledger-app.streamlit.app/',
            # --- END UPDATED URLS ---
        )
        return session.url, None
    except Exception as e:
        return None, str(e)

def check_subscription_status(user_id, stripe_customer_id):
    """Pings Stripe to see if the user has an active/trialing subscription."""
    try:
        if not stripe_customer_id:
            return False
            
        subs = stripe.Subscription.list(customer=stripe_customer_id, status='all', limit=1)
        if subs.data:
            sub = subs.data[0]
            # Allow: active, trialing
            if sub.status in ['active', 'trialing']:
                # Update DB to match Stripe
                conn.execute("UPDATE users SET subscription_status = ?, stripe_subscription_id = ? WHERE id = ?", 
                             ('Active', sub.id, user_id))
                conn.commit()
                return True
        return False
    except Exception as e:
        st.error(f"Error checking subscription: {e}")
        return False

# --- AUTHENTICATION INIT ---

credentials = load_credentials()
authenticator = stauth.Authenticate(
    credentials, 
    'ar_ledger_cookie', 
    'velazco_key_beta_2025', 
    cookie_expiry_days=30
)

if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# --- UI START ---

if BB_LOGO_PATH and os.path.exists(BB_LOGO_PATH):
    st.image(BB_LOGO_PATH, width=200)

if not st.session_state.authenticated:
    st.title("Client AR Portal")
    st.caption(BB_WATERMARK)

    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        try:
            authenticator.login(location='main')
        except LoginError as e:
            st.error("Username or password is incorrect")
        
        if st.session_state["authentication_status"]:
            username = st.session_state["username"].strip()
            
            c = conn.cursor()
            # We fetch stripe_customer_id to check status later
            c.execute("SELECT id, subscription_status, stripe_customer_id FROM users WHERE username = ? COLLATE NOCASE", (username,))
            user_record = c.fetchone()
            
            if user_record:
                db_id, sub_status, stripe_cid = user_record
                
                # We authenticate them, but the "Gatekeeper" logic comes later
                st.session_state.user_id = db_id
                st.session_state.stripe_cid = stripe_cid
                st.session_state.sub_status = sub_status
                st.session_state.authenticated = True
                st.rerun() 
            else:
                st.error("User record not found in database.")
                authenticator.logout('Reset Login Session', 'main') 

        elif st.session_state["authentication_status"] is False:
            st.error('Username/password is incorrect')
        elif st.session_state["authentication_status"] is None:
            st.warning('Please enter your username and password')

    with tab2:
        with st.form("signup_form"):
            st.subheader("Create New Account")
            new_user = st.text_input("Username").strip()
            new_pass = st.text_input("Password", type="password")
            new_email = st.text_input("Email").strip()
            
            # --- REFERRAL INPUT ---
            referral_input = st.text_input("Referral Code (Optional)")
            
            st.markdown("[View Terms and Conditions](https://balanceandbuildconsulting.com/wp-content/uploads/2025/12/Balance-Build-Consulting-LLC_Software-as-a-Service-SaaS-Terms-of-Service-and-Privacy-Policy.pdf)")
            
            accept_terms = st.checkbox("I accept the Balance & Build Terms of Service")
            submitted = st.form_submit_button("Sign Up")
            
            if submitted:
                if accept_terms:
                    if new_user and new_pass and new_email:
                        try:
                            # 1. Hash Password
                            hashed_pw = hash_password(new_pass)
                            
                            # 2. Generate Own Referral Code
                            my_ref_code = generate_referral_code()
                            
                            # 3. Create Stripe Customer
                            stripe_cid = create_stripe_customer(new_email, new_user)
                            
                            if stripe_cid:
                                # 4. Handle Referral Logic (Increment referrer's count)
                                if referral_input:
                                    conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE referral_code = ?", (referral_input,))
                                
                                # 5. Insert User (Status is 'Inactive' initially)
                                c = conn.cursor()
                                c.execute("""
                                    INSERT INTO users (username, password, email, accepted_terms, subscription_status, stripe_customer_id, referral_code, referred_by) 
                                    VALUES (?, ?, ?, ?, 'Inactive', ?, ?, ?)
                                """, (new_user, hashed_pw, new_email, 1, stripe_cid, my_ref_code, referral_input))
                                conn.commit()
                                
                                st.success("Account created! Please log in to start your subscription.")
                                credentials = load_credentials() # Refresh auth
                            else:
                                st.error("Could not connect to billing system. Please try again.")
                                
                        except sqlite3.IntegrityError:
                            st.error("Username already taken. Please choose another.")
                    else:
                        st.error("Please fill in all fields.")
                else:
                    st.error("You must accept the terms to create an account.")

# --- SUBSCRIPTION GATEKEEPER ---

if st.session_state.authenticated and st.session_state.user_id:
    user_id = st.session_state.user_id
    stripe_cid = st.session_state.get('stripe_cid')
    current_status = st.session_state.get('sub_status', 'Inactive')
    
    # Check if we need to block access
    if current_status != 'Active':
        st.warning("⚠️ No Active Subscription Found")
        st.write("You are one step away! Start your 30-day free trial to access the AR Ledger.")
        
        # 1. Button to generate Stripe Link
        if stripe_cid:
            checkout_url, err = create_checkout_session(stripe_cid)
            if checkout_url:
                st.link_button("👉 Start 30-Day Free Trial (Secure Checkout)", checkout_url)
            elif err:
                st.error(f"Configuration Error: {err}")
        else:
            st.error("Billing account missing. Contact support.")
            
        st.divider()
        st.write("Already subscribed?")
        if st.button("Check Subscription Status"):
            is_active = check_subscription_status(user_id, stripe_cid)
            if is_active:
                st.session_state.sub_status = 'Active'
                st.success("Subscription verified! Welcome aboard.")
                st.rerun()
            else:
                st.error("We couldn't find an active subscription yet. Please complete checkout above.")
        
        if st.button("Logout"):
            authenticator.logout('Logout', 'main')
            st.session_state.authenticated = False
            st.rerun()
            
        st.stop() # STOP HERE if not active

    # --- MAIN APP (ONLY RUNS IF ACTIVE) ---
    
    # Fetch User Config & Company Info
    c = conn.cursor()
    # CHANGE: Replaced logo_path with logo_data
    c.execute("SELECT logo_data, terms_conditions, email, company_name, company_address, company_phone, referral_code, referral_count FROM users WHERE id = ?", (user_id,))
    user_data = c.fetchone()
    
    if user_data:
        user_logo_data = user_data[0] # NEW VARIABLE NAME
        user_terms = user_data[1] or "Standard Terms & Conditions applied."
        user_email = user_data[2]
        company_name = user_data[3] or "My Company"
        company_address = user_data[4] or ""
        company_phone = user_data[5] or ""
        my_ref_code = user_data[6]
        my_ref_count = user_data[7]
        
        company_info = {
            'name': company_name,
            'address': company_address,
            'phone': company_phone,
            'email': user_email
        }
    else:
        st.error("Critical Error: User data lost. Please re-login.")
        st.stop()

    st.title(f"{company_name} AR Ledger")
    st.caption(BB_WATERMARK)

    with st.sidebar:
        display_name = st.session_state.get('name', 'User')
        st.header(f"Hello, {display_name}")
        page = st.radio("Navigate", ["Dashboard", "Projects", "Contacts", "Invoices", "Payments", "Reports", "Settings", "Help"])
        st.divider()
        if st.button("Logout"):
            authenticator.logout('Logout', 'main')
            st.session_state.authenticated = False
            st.rerun()

    send_reminders(user_id)

    # --- DASHBOARD ---
    if page == "Dashboard":
        d_col1, d_col2 = st.columns([3, 1])
        with d_col1:
            st.subheader("Financial Dashboard")
        with d_col2:
            # CHANGE: Display logo from data
            if user_logo_data:
                st.image(user_logo_data, width=150)
            else:
                st.write("") # Placeholder to maintain column spacing
                
        projects = get_user_data(user_id, "projects")
        
        if not projects.empty:
            col1, col2, col3 = st.columns(3)
            
            total_ar = 0.0
            total_invoiced = 0.0
            total_collected = 0.0
            
            all_inv = get_user_data(user_id, "invoices")
            all_pay = get_user_data(user_id, "payments")
            
            if not all_inv.empty:
                total_invoiced = all_inv['amount'].sum()
            if not all_pay.empty:
                total_collected = all_pay['amount'].sum()
            
            total_ar = total_invoiced - total_collected

            col1.metric("Total Invoiced", f"${total_invoiced:,.2f}")
            col2.metric("Total Collected", f"${total_collected:,.2f}")
            col3.metric("Outstanding AR", f"${total_ar:,.2f}", delta_color="inverse")
            
            st.divider()
            
            st.subheader("Project Breakdowns")
            for _, project in projects.iterrows():
                pid = int(project['id'])
                
                with st.expander(f"{project['name']} (Client: {project['client_name']})"):
                    # Recalculate Project Specific Metrics
                    quoted = project['quoted_price']
                    p_inv = get_user_data(user_id, "invoices", f"AND project_id = {pid}")
                    p_pay = get_user_data(user_id, "payments", f"AND project_id = {pid}")
                    
                    p_invoiced = p_inv['amount'].sum() if not p_inv.empty else 0.0
                    p_collected = p_pay['amount'].sum() if not p_pay.empty else 0.0
                    
                    # New Calculations
                    p_balance = p_invoiced - p_collected # Balance Due to Receive
                    remaining_budget = quoted - p_invoiced # Remaining Balance to Invoice
                    
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        st.write(f"**Quoted:** ${quoted:,.2f}")
                        st.write(f"**Invoiced:** ${p_invoiced:,.2f}")
                        st.write(f"**Collected:** ${p_collected:,.2f}")
                        
                        # Updated Metrics
                        st.markdown("---")
                        st.write(f"**Balance Due to Receive:** ${p_balance:,.2f}")
                        st.write(f"**Remaining to Invoice:** ${remaining_budget:,.2f}")
                        st.markdown("---")
                    
                    with c2:
                        # Simple Bar Chart for this project
                        chart_data = pd.DataFrame({
                            'Metric': ['Invoiced', 'Collected'],
                            'Amount': [p_invoiced, p_collected]
                        })
                        c = alt.Chart(chart_data).mark_bar().encode(
                            x='Metric',
                            y='Amount',
                            color='Metric'
                        ).properties(height=200)
                        st.altair_chart(c, use_container_width=True)

        else:
            st.info("No active projects found. Go to 'Projects' to add one.")

    # --- PROJECTS ---
    elif page == "Projects":
        st.subheader("Project Management")
        
        with st.expander("Add New Project", expanded=False):
            with st.form("add_project"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Project Name")
                client_name = c2.text_input("Client Name")
                quoted_price = c1.number_input("Quoted Price ($)", min_value=0.0)
                start_date = c2.date_input("Start Date")
                duration = c1.number_input("Duration (Days)", min_value=0)
                address = c2.text_input("Site Address")
                priority = st.slider("Priority", 1, 5, 3)
                
                if st.form_submit_button("Add Project"):
                    if name and client_name:
                        conn.execute("""
                            INSERT INTO projects (user_id, name, client_name, quoted_price, start_date, duration, address, priority) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (user_id, name, client_name, quoted_price, start_date, duration, address, priority))
                        conn.commit()
                        log_audit(user_id, f"Added Project: {name}")
                        st.success("Project Added!")
                        st.rerun()
                    else:
                        st.error("Name and Client Name are required.")

        projects = get_user_data(user_id, "projects")
        if not projects.empty:
            st.dataframe(projects.drop(columns=['user_id']))
            
            st.divider()
            st.write("Danger Zone")
            p_to_delete = st.selectbox("Select Project to Delete", projects['name'])
            if st.button("Delete Project"):
                pid = projects[projects['name'] == p_to_delete]['id'].values[0]
                conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
                conn.execute("DELETE FROM invoices WHERE project_id = ?", (pid,))
                conn.execute("DELETE FROM payments WHERE project_id = ?", (pid,))
                conn.execute("DELETE FROM contacts WHERE project_id = ?", (pid,))
                conn.commit()
                log_audit(user_id, f"Deleted Project: {p_to_delete}")
                st.warning(f"Deleted {p_to_delete}")
                st.rerun()

        st.divider()
        if st.button("Create Database Backup (Zip)"):
            with zipfile.ZipFile("backup.zip", "w") as zipf:
                zipf.write(DB_FILE)
            with open("backup.zip", "rb") as f:
                st.download_button("Download Backup", f, "ar_ledger_backup.zip")

    # --- CONTACTS ---
    elif page == "Contacts":
        st.subheader("Contacts")
        projects = get_user_data(user_id, "projects")
        
        if not projects.empty:
            project_choice = st.selectbox("Select Project", projects['name'])
            project_id = int(projects[projects['name'] == project_choice]['id'].values[0])
            
            with st.form("new_contact"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Contact Name")
                email = c2.text_input("Email")
                phone = c1.text_input("Phone")
                is_primary = c2.checkbox("Primary Contact")
                
                if st.form_submit_button("Add Contact"):
                    conn.execute("""
                        INSERT INTO contacts (user_id, project_id, name, email, phone, is_primary) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (user_id, project_id, name, email, phone, is_primary))
                    conn.commit()
                    st.success("Contact Added")
            
            contacts = get_user_data(user_id, "contacts", f"AND project_id = {project_id}")
            if not contacts.empty:
                st.write("Project Contacts:")
                st.dataframe(contacts[['name', 'email', 'phone', 'is_primary']])
        else:
            st.info("Create a project first.")

    # --- INVOICES ---
    elif page == "Invoices":
        st.subheader("Invoicing")
        projects = get_user_data(user_id, "projects")
        
        if not projects.empty:
            project_choice = st.selectbox("Select Project", projects['name'])
            project_row = projects[projects['name'] == project_choice].iloc[0]
            project_id = int(project_row['id'])
            quoted = project_row['quoted_price']
            
            current_invoices = get_user_data(user_id, "invoices", f"AND project_id = {project_id}")
            total_invoiced_so_far = current_invoices['amount'].sum() if not current_invoices.empty else 0.0
            remaining_budget = quoted - total_invoiced_so_far
            
            st.info(f"Budget Remaining to Invoice: ${remaining_budget:,.2f} (Quoted: ${quoted:,.2f})")
            
            with st.form("invoice_form"):
                amount = st.number_input("Invoice Amount", min_value=0.01)
                inv_date = st.date_input("Date", datetime.date.today())
                desc = st.text_area("Description / Line Items")
                c1, c2 = st.columns(2)
                tax = c1.number_input("Tax", min_value=0.0)
                discount = c2.number_input("Discount", min_value=0.0)
                
                submitted = st.form_submit_button("Generate Invoice")
                if submitted:
                    if amount > remaining_budget + 1.0: 
                         st.warning("Warning: This amount exceeds the remaining quoted budget.")
                    
                    inv_num = len(get_user_data(user_id, "invoices")) + 1000 
                    
                    conn.execute("""
                        INSERT INTO invoices (user_id, project_id, number, amount, date, description, tax, discount) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, project_id, inv_num, amount, inv_date, desc, tax, discount))
                    conn.commit()
                    log_audit(user_id, f"Issued Invoice #{inv_num}")
                    
                    inv_data = {
                        'number': inv_num, 'amount': amount, 'date': inv_date, 
                        'description': desc, 'tax': tax, 'discount': discount
                    }
                    pdf_bytes = generate_pdf_invoice(inv_data, user_logo, company_info, user_terms)
                    
                    st.session_state['last_invoice_pdf'] = pdf_bytes
                    st.session_state['last_invoice_num'] = inv_num
                    
                    st.success("Invoice Recorded!")
                    if user_email:
                        send_email(user_email, f"Invoice #{inv_num} Generated", "Attached.")
            
            if 'last_invoice_pdf' in st.session_state:
                st.download_button(
                    label="Download Last Invoice PDF",
                    data=st.session_state['last_invoice_pdf'],
                    file_name=f"Invoice_{st.session_state['last_invoice_num']}.pdf",
                    mime="application/pdf"
                )
            
            st.divider()
            st.write("Invoice History")
            if not current_invoices.empty:
                st.dataframe(current_invoices)
                
        else:
            st.info("Create a project first.")

    # --- PAYMENTS ---
    elif page == "Payments":
        st.subheader("Record Payments")
        projects = get_user_data(user_id, "projects")
        
        if not projects.empty:
            project_choice = st.selectbox("Select Project", projects['name'])
            project_id = int(projects[projects['name'] == project_choice]['id'].values[0])
            
            with st.form("payment_form"):
                amount = st.number_input("Payment Received ($)", min_value=0.01)
                pay_date = st.date_input("Date Received", datetime.date.today())
                form = st.selectbox("Payment Method", ["Check", "Cash", "Wire/ACH", "Credit Card"])
                ref_num = st.text_input("Reference/Check #")
                
                if st.form_submit_button("Record Payment"):
                    conn.execute("""
                        INSERT INTO payments (user_id, project_id, amount, date, form, check_number) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (user_id, project_id, amount, pay_date, form, ref_num))
                    conn.commit()
                    log_audit(user_id, "Recorded Payment")
                    st.success("Payment Recorded!")
                    st.rerun()
            
            pay_history = get_user_data(user_id, "payments", f"AND project_id = {project_id}")
            if not pay_history.empty:
                st.write("Payment History:")
                st.dataframe(pay_history)
        else:
            st.info("Create a project first.")

    # --- REPORTS ---
    elif page == "Reports":
        st.subheader("Reports & Analytics")
        
        invoices = get_user_data(user_id, "invoices")
        
        if not invoices.empty:
            st.write("### Aging Report")
            invoices['date'] = pd.to_datetime(invoices['date'])
            invoices['age'] = (pd.Timestamp.now() - invoices['date']).dt.days
            
            bins = [0, 30, 60, 90, 9999]
            labels = ['0-30 Days', '31-60 Days', '61-90 Days', '90+ Days']
            invoices['Aging Bucket'] = pd.cut(invoices['age'], bins=bins, labels=labels)
            
            aging_summary = invoices.groupby('Aging Bucket', observed=False)['amount'].sum().reset_index()
            
            c = alt.Chart(aging_summary).mark_bar().encode(
                x='Aging Bucket',
                y='amount',
                color='Aging Bucket',
                tooltip=['Aging Bucket', 'amount']
            ).properties(title="Accounts Receivable Aging")
            st.altair_chart(c, use_container_width=True)
            
            st.write("### Audit Logs")
            logs = pd.read_sql_query("SELECT action, timestamp FROM audit_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50", conn, params=(user_id,))
            st.dataframe(logs)
            
            st.download_button("Export All Invoices (CSV)", invoices.to_csv(index=False).encode('utf-8'), "invoices.csv")
        else:
            st.info("No data to report yet.")

    # --- SETTINGS ---
    elif page == "Settings":
        st.subheader("Settings")
        
        # New: Referral Tracker
        st.info(f"🎁 **Refer & Earn:** You have referred **{my_ref_count}** people so far! Share your code: `{my_ref_code}`")
        
        st.write("### Company Profile")
        with st.form("company_info_form"):
            c_name = st.text_input("Company Name", value=company_name)
            c_addr = st.text_input("Company Address", value=company_address)
            c_phone = st.text_input("Company Phone", value=company_phone)
            
            if st.form_submit_button("Save Company Info"):
                conn.execute("""
                    UPDATE users 
                    SET company_name = ?, company_address = ?, company_phone = ? 
                    WHERE id = ?
                """, (c_name, c_addr, c_phone, user_id))
                conn.commit()
                st.success("Company info updated! This will appear on your Invoices and Dashboard.")
                st.rerun()

        st.divider()
        st.write("### Branding")
        logo_upload = st.file_uploader("Upload Company Logo (PNG/JPG)")
        if logo_upload:
            file_path = os.path.join(USER_LOGOS_DIR, f"{user_id}_{logo_upload.name}")
            with open(file_path, "wb") as f:
                f.write(logo_upload.getbuffer())
            
            conn.execute("UPDATE users SET logo_path = ? WHERE id = ?", (file_path, user_id))
            conn.commit()
            st.success("Logo updated! It will appear on your next Invoice.")
            st.rerun()

        st.divider()
        st.write("### Terms & Conditions")
        current_terms = user_terms
        new_terms = st.text_area("Default Invoice Terms", value=current_terms, height=150)
        
        if st.button("Save Terms"):
            conn.execute("UPDATE users SET terms_conditions = ? WHERE id = ?", (new_terms, user_id))
            conn.commit()
            st.success("Terms saved.")

    # --- HELP ---
    elif page == "Help":
        st.subheader("Help Guide")
        st.markdown("""
        **1. Dashboard:** View high-level financials and project breakdown.
        **2. Projects:** Add new jobs here first. You cannot create invoices or contacts without a project.
        **3. Contacts:** Store client details for specific projects.
        **4. Invoices:** Generate PDF invoices. This checks against your quoted budget.
        **5. Payments:** Record checks, cash, or wire transfers to offset the invoice balances.
        **6. Settings:** Set your Company Name, Address, Logo, and Legal Terms. Check referral stats.
        """)

# --- FOOTER ---
st.markdown("---")

st.markdown(f"<div style='text-align: center; color: grey;'>{BB_WATERMARK}</div>", unsafe_allow_html=True)



