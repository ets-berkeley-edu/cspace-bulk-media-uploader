FROM python:3.11-slim
WORKDIR /app
# The pinned dependencies first, checked against their hashes, so a change to the code alone reuses this layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml ./
COPY bmu ./bmu
COPY fakecspace ./fakecspace
# The BMU itself downloads nothing: its dependencies and setuptools came from requirements.txt.
# Make the code readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && chmod -R a+rX /app && useradd -r -u 10001 bmu
USER bmu
EXPOSE 8000
CMD ["uvicorn", "bmu.main:app", "--host", "0.0.0.0", "--port", "8000"]
