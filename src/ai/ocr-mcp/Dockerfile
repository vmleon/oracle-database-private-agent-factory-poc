FROM docker.io/python:3.12-slim

WORKDIR /app

# Install deps first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./

ENV PORT=8501 \
    HOST=0.0.0.0

EXPOSE 8501

CMD ["python", "server.py"]
