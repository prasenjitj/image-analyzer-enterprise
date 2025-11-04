FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy and install requirements first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy essential application files
COPY . .

# Create runtime directories (ensure they exist)
RUN mkdir -p uploads exports logs temp checkpoints

# Expose port (Cloud Functions will override)
EXPOSE 8080

# For Cloud Run/container usage, run container-friendly server (0.0.0.0:$PORT)
CMD ["python", "server/run_server_cloud.py"]
