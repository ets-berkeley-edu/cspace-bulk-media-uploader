"""Starts the simulated CollectionSpace (the fakecspace package) with the BMU's samples already in PAHMA's store.

The package starts empty (its F9): each app seeds the sample set it needs. The BMU's set (14 Objects and a Media record
15-1234 with no file) is seeded here, in the same process, before the server takes a request, so every start has it:
./bmu up, ./bmu test, and an AWS environment's simulator after a pause, a deploy or a restart. A reset
(POST /_fake/reset) empties it again; the Demo tools seed the set after theirs (backend/bmu/demo.py).

deploy/fakecspace.Dockerfile runs this; it isn't part of the BMU's own images.
"""
import uvicorn
from fakecspace import seeds
from fakecspace.app import app, stores

seeds.seed(stores["pahma"], "bmu")
uvicorn.run(app, host="0.0.0.0", port=8180, server_header=False)  # noqa: S104 (in a container, on a private network)
