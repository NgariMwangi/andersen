# Sales Management System - Docker image
FROM python:3.12-slim

# Create app user and directory
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Install system deps for psycopg2 and reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

# Non-root user
USER appuser

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1
EXPOSE 5001

# Run with Flask built-in server (simple, single process; no gunicorn)
CMD ["python", "run.py"]
