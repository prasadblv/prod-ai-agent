FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY tests/ ./tests/
COPY main.py app.py dashboard.html ./

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
EXPOSE 9464

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]




