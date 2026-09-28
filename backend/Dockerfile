FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY bmu ./bmu
COPY fakecspace ./fakecspace
RUN pip install --no-cache-dir . && useradd -r -u 10001 bmu
USER bmu
EXPOSE 8000
CMD ["uvicorn", "bmu.main:app", "--host", "0.0.0.0", "--port", "8000"]
