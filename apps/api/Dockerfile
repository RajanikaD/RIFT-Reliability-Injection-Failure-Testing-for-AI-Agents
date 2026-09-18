FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps/api/src ./apps/api/src
COPY packages/rift_core/src ./packages/rift_core/src

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "rift_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

