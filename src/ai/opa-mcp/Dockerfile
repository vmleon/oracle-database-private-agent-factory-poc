FROM docker.io/python:3.12-slim

WORKDIR /app

# Install deps first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py opa_client.py ./

ENV PORT=8500 \
    HOST=0.0.0.0 \
    OPA_URL=http://opa:8181

EXPOSE 8500

CMD ["python", "server.py"]
