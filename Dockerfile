# Andersen HRMS - Docker image
FROM python:3.12-slim

# Create app user and directory
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Install system deps for psycopg2; gosu drops root after fixing upload volume permissions
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1
EXPOSE 5002

# Entrypoint runs as root to chown /employeeuploads, then exec as appuser
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "run.py"]
