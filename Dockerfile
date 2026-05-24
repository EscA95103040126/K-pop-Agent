FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    FLASK_DEBUG=0 \
    DATABASE_PATH=data/chart_history.db \
    MOCK_DATA_DIR=data/mock

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python scripts/init_db.py && \
    if [ ! -s data/chart_history.db ]; then python scripts/seed_data.py; fi

EXPOSE 7860

CMD ["python", "app.py"]
