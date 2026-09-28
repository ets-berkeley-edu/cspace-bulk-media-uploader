FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY bmu ./bmu
COPY fakecspace ./fakecspace
# Make the code readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN pip install --no-cache-dir . && chmod -R a+rX /app && useradd -r -u 10001 bmu
USER bmu
EXPOSE 8000
CMD ["uvicorn", "bmu.main:app", "--host", "0.0.0.0", "--port", "8000"]
