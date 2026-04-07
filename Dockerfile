FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# O image do Playwright já inclui browsers. Garantimos o Chromium disponível.
RUN python -m playwright install --with-deps chromium

# Copia o projeto
COPY . /app

# Render injeta $PORT; default local = 8000
CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

