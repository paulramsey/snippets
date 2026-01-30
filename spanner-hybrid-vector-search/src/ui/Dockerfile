FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (if separate) or just install inline for this simple app
# We'll install directly to keep it self-contained in one file if possible, 
# but best practice is requirements.txt. 
# Let's create a requirements.txt in the same dir? 
# Or just run pip install.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables (overridden at runtime)
ENV PORT=8080

# Run with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "0", "app:app"]
