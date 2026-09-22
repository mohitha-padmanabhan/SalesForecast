FROM python:3.12-slim

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        unixodbc \
        unixodbc-dev \
        libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

# Add Microsoft package repository
RUN curl -sSL -O https://packages.microsoft.com/config/debian/13/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb
    
# Install Microsoft ODBC Driver 18
RUN ACCEPT_EULA=Y apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Application directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app ./app

# Start FastAPI
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}