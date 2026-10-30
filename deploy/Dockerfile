# Production image for AWS: the FastAPI web app serving the built Vue app, and the worker (same image, other command).
# Build from the repository root (./bmu aws deploy does this):
#   docker build --platform linux/arm64 -f deploy/Dockerfile -t bmu .
# The local Docker Compose stack doesn't use this image (it runs backend/Dockerfile and the Vue dev server).
# Base images come from Amazon ECR Public's copies of the Docker official images (no Docker Hub rate limits).
# Each is pinned by digest as well as tag (review 5.7), so a tag moved upstream changes nothing until Dependabot
# proposes the new digest. ECR Public mirrors the official images unchanged, so the digests match Docker Hub's.

# ---- the Vue app: a production build, so the Demo tools pane is left out of the bundle ----------------------------
FROM public.ecr.aws/docker/library/node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend
# eMudhra CA compromise (Oct 2026): Node 22.23.4 refuses the compromised CAs itself, but Alpine's system bundle
# (curl, wget, OpenSSL) needs ca-certificates 20261020-r0; the build fails if the bundle still holds the emSign root.
RUN apk add --no-cache --upgrade ca-certificates-bundle \
    && node -e 'const {X509Certificate} = require("crypto"); const pem = require("fs").readFileSync("/etc/ssl/certs/ca-certificates.crt", "utf8").match(/-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----/g); if (pem.some(p => new X509Certificate(p).fingerprint256.startsWith("86:A1:EC:BA"))) { console.error("The system CA bundle still holds emSign ECC Root CA - G3"); process.exit(1); }'
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- the Python app ---------------------------------------------------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.11-slim-trixie@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
# eMudhra CA compromise (Oct 2026): take Debian's fixed ca-certificates even if the base image predates it;
# the build fails if the installed version is older than the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BMU_STATIC_DIR=/app/static
WORKDIR /app
# The pinned dependencies first, checked against their hashes, so a change to the code alone reuses this layer.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY backend/pyproject.toml ./
COPY backend/bmu ./bmu
# Not the simulated CollectionSpace (the fakecspace package): it has its own image (deploy/fakecspace.Dockerfile).
# The BMU itself downloads nothing: its dependencies and setuptools came from requirements.txt.
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd -r -u 10001 bmu
COPY --from=frontend /src/dist ./static
# Readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN chmod -R a+rX /app
USER bmu
EXPOSE 8000
# The web app. The worker's task runs: python -m bmu.worker
CMD ["uvicorn", "bmu.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
