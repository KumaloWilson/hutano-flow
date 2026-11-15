FROM python:3.12.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN useradd --create-home --uid 10001 hutano
COPY requirements.txt requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.lock
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests
COPY pytest.ini .
RUN mkdir -p /app/artifacts && chown -R hutano:hutano /app
USER hutano

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

