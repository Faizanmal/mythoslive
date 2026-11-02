FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/tests ./tests
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY frontend/src/lib/contracts.generated.ts /workspace/frontend/src/lib/contracts.generated.ts
RUN pip install --no-cache-dir '.[dev]'
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
