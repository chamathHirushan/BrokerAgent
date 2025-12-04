# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# - build-essential: for compiling some python packages
# - curl: for healthchecks or downloading tools
# - git: if you need to clone repos (optional)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy the requirements file into the container
COPY requirements.txt .

# Increase timeout for large downloads (like torch/nvidia libs)
ENV UV_HTTP_TIMEOUT=600

# Install Python dependencies using uv
# We use --system to install into the system python environment, avoiding venv complexity in Docker
# 1. Install PyTorch CPU version first to prevent downloading huge CUDA wheels
RUN uv pip install --system torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. Install the rest of the dependencies
RUN uv pip install --system -r requirements.txt

# Install Playwright browsers and system dependencies
RUN playwright install chromium && playwright install-deps chromium

# Copy the rest of the application code
COPY . .

# Create directories for data persistence
RUN mkdir -p downloads analysis_results

# Expose the port the app runs on
EXPOSE 8000

# Define environment variable for unbuffered output
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Command to run the application
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
