FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY app/ app/

# Persistent volume mount point for SQLite history
RUN mkdir -p /data
ENV HISTORY_DB_PATH=/data/history.db
# Ensure the data directory is writable at runtime via a mounted volume

EXPOSE 8000

CMD ["python", "main.py"]
