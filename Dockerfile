FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
ENV PORT=8080 CK_STORE=gcp
CMD exec uvicorn canonkeeper.api:app --host 0.0.0.0 --port $PORT
