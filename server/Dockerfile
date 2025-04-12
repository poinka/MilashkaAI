# Base Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt requirements.txt

# Install dependencies
# Consider using --no-cache-dir to reduce image size
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY ./app /app/app

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
