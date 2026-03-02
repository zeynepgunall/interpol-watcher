FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY web /app/web
COPY shared /app/shared

ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=web.app:app

EXPOSE 8000

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=8000"]

