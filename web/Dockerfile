FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY web /app/web
COPY shared /app/shared

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "4", "-b", "0.0.0.0:8000", "--timeout", "120", "web.app:app"]