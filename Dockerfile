# Use a lightweight version of Python
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose Port 8080
EXPOSE 8080


CMD mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml && streamlit run ar_ledger_app.py
