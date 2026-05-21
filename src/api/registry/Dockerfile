FROM docker.io/python:3.12-slim

WORKDIR /app

# Install deps first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py data.json ./

ENV PORT=8600 \
    HOST=0.0.0.0

EXPOSE 8600

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8600"]
