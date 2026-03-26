FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5001", "--timeout", "300", "app:app"]
