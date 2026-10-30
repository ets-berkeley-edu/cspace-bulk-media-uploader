# The simulated CollectionSpace: the fakecspace package (github.com/ets-berkeley-edu/cspace-fakecspace), pinned with its
# hash in backend/requirements-sim.in. The image for the local stacks' fakecspace service (docker-compose.yml: ./bmu up,
# ./bmu test) and for an AWS environment with SIMULATED_CSPACE=true. Its own image, so neither of the BMU's images
# (backend/Dockerfile, deploy/Dockerfile) contains the simulator. Build from the repository root (./bmu aws deploy and
# docker compose do this):
#   docker build --platform linux/arm64 -f deploy/fakecspace.Dockerfile -t fakecspace .
# It isn't CollectionSpace: its accounts are synthetic and their passwords public (each is its user name), and its data
# is in memory.
FROM public.ecr.aws/docker/library/python:3.11-slim-trixie@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
# eMudhra CA compromise (Oct 2026): take Debian's fixed ca-certificates even if the base image predates it;
# the build fails if the installed version is older than the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
# The simulator and what it needs (FastAPI, uvicorn...), checked against their hashes and held to the BMU's versions
# (requirements-sim.txt); none of the BMU's other dependencies.
COPY backend/requirements-sim.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-sim.txt
# Seeds the BMU's samples, then serves on port 8180.
COPY deploy/fakecspace_start.py ./
# Readable by the non-root user whatever file modes the checkout has (e.g. a umask of 077).
RUN chmod -R a+rX /app && useradd -r -u 10001 fakecspace
USER fakecspace
EXPOSE 8180
CMD ["python", "fakecspace_start.py"]
