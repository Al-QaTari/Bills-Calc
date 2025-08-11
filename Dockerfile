# =============================================================================
# Treasury Bills Calculator - Docker Configuration
# حاسبة أذون الخزانة - إعداد Docker
# =============================================================================

# Base image
FROM python:3.11-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

# Install system dependencies (including gosu)
COPY packages.txt /tmp/
RUN apt-get update && \
    apt-get install -y --no-install-recommends $(cat /tmp/packages.txt) && \
    rm -rf /var/lib/apt/lists/*

# Create user and working directory
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser/app

# Update PATH variable
ENV PATH="/home/appuser/.local/bin:${PATH}"

# Copy files and install libraries (ownership will be set via entrypoint)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

COPY . .

# Set entrypoint
ENTRYPOINT ["/home/appuser/app/entrypoint.sh"]

# Expose port and set default command
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
