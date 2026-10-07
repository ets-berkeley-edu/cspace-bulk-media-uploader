# The simulated CollectionSpace (backend/fakecspace) for an AWS environment with SIMULATED_CSPACE=true. Its own image,
# so the BMU's production image (deploy/Dockerfile) never contains the simulator. Build from the repository root
# (./bmu aws deploy does this):
#   docker build --platform linux/arm64 -f deploy/fakecspace.Dockerfile -t fakecspace .
# It isn't CollectionSpace: its accounts' passwords are public (backend/fakecspace/app.py) and its data is in memory.
FROM public.ecr.aws/docker/library/python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
# The same pinned dependencies as the BMU, checked against their hashes (it needs FastAPI, uvicorn, python-multipart
# and defusedxml from them).
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY backend/fakecspace ./fakecspace
# Readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN chmod -R a+rX /app && useradd -r -u 10001 fakecspace
USER fakecspace
EXPOSE 8180
CMD ["uvicorn", "fakecspace.app:app", "--host", "0.0.0.0", "--port", "8180", "--no-server-header"]
