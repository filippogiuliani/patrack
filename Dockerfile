# 1) Build the frontend (Svelte + Vite)
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# famkit/ui: shared frontend parts, reached as ../backend/famkit/ui (see vite.config.js)
COPY backend/famkit/ui /backend/famkit/ui
RUN npx vite build --outDir /web/dist

# 2) Flask backend serving the API and the frontend, with Tesseract for OCR (Italian + English)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Rome
RUN apt-get update && apt-get install -y --no-install-recommends tzdata tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/*.py ./
# famkit: the shared code (git submodule: clone with --recurse-submodules or run "git submodule update --init")
COPY backend/famkit/*.py ./famkit/
COPY --from=web /web/dist ./static
# Data (database, encrypted files, key, backups) lives in the volume mounted on /app/data
EXPOSE 3002
CMD ["python", "app.py"]
