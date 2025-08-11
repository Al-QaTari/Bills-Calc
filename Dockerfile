FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

COPY packages.txt /tmp/
RUN apt-get update && \
    apt-get install -y --no-install-recommends $(cat /tmp/packages.txt) && \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser/app

ENV PATH="/home/appuser/.local/bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m playwright install --with-deps chromium && \
    pip install pip-audit && \
    pip-audit

COPY . .

ENTRYPOINT ["/home/appuser/app/entrypoint.sh"]

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
