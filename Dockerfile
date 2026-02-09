FROM python:3.11-slim

RUN apt update && apt install -y curl iputils-ping gcc libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads

RUN python .api/build.py || true

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Run Uvicorn with multiple workers to avoid single-process blocking causing 504s.
# Use UVICORN_WORKERS env var (default 2) to control worker count from docker-compose.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4} --timeout-keep-alive 30"]
