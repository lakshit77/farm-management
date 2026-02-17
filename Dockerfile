# Showground Live Monitoring API - Production image for AWS EC2
# Python 3.11 slim for smaller image size
FROM python:3.11-slim

# Prevent Python from writing pyc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy dependency file first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (alembic, app, alembic.ini)
COPY alembic ./alembic
COPY alembic.ini .
COPY app ./app

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Expose API port (used by n8n and other clients)
EXPOSE 8000

# Bind to 0.0.0.0 so the API is reachable from outside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
