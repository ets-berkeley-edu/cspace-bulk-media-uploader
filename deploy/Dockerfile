# Production image for AWS: the FastAPI web app serving the built Vue app, and the worker (same image, other command).
# Build from the repository root (./bmu aws deploy does this):
#   docker build --platform linux/arm64 -f deploy/Dockerfile -t bmu .
# The local Docker Compose stack doesn't use this image (it runs backend/Dockerfile and the Vue dev server).
# Base images come from Amazon ECR Public's copies of the Docker official images (no Docker Hub rate limits).

# ---- the Vue app: a production build, so the Demo tools pane is left out of the bundle ----------------------------
FROM public.ecr.aws/docker/library/node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- the Python app ---------------------------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BMU_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/bmu ./bmu
COPY backend/fakecspace ./fakecspace
RUN pip install --no-cache-dir . && useradd -r -u 10001 bmu
COPY --from=frontend /src/dist ./static
# Readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN chmod -R a+rX /app
USER bmu
EXPOSE 8000
# The web app. The worker's task runs: python -m bmu.worker
CMD ["uvicorn", "bmu.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
