# Pinned slim base image (not "latest") - reproducible builds, smaller attack surface
FROM python:3.12-slim

# Create a non-root user; the restricted Pod Security Standard requires non-root
RUN useradd --create-home --uid 1001 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# Drop to the unprivileged user for runtime
USER 1001

EXPOSE 8080
CMD ["python", "app.py"]
