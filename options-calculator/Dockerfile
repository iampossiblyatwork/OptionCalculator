# Options Premium Calculator — Flask app, container ready for Render.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Render injects $PORT at runtime; gunicorn binds to it (falls back to 8000
# locally). Shell form so ${PORT} is expanded.
CMD gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60 app:app
