# Dockerfile - build a minimal production image for Envital backend
FROM python:3.11-slim

# system deps (h3 needs a C compiler occasionally; keep lean)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copy pyproject/requirements or fallback to requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy code
COPY . /app

# Ensure entrypoint is executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose the port (uvicorn will use 8000)
EXPOSE 8000

# Default command runs entrypoint which will start migrations & uvicorn
CMD ["/app/entrypoint.sh"]
