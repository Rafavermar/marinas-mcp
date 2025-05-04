# 1. Base ligera
FROM python:3.11-slim

# 2. Variables de entorno
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS=chromium

# 3. Instala dependencias de sistema + Playwright
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcairo2 \
    libgbm1 libglib2.0-0 libgtk-3-0 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 libxss1 libxtst6 fonts-liberation curl \
 && rm -rf /var/lib/apt/lists/*

# 4. Directorio de trabajo
WORKDIR /app

# 5. Instala dependencias de Python
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && playwright install --with-deps chromium

# 6. Copia el resto de tu código
COPY . .

# 7. Expón el puerto que usa FastMCP/uvicorn
EXPOSE 8000

# 8. Comando de arranque: uvicorn sobre el FastMCP.app
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
