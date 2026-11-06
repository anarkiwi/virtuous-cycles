FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb AS base
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY requirements-dev.txt /tmp/
RUN pip install -r /tmp/requirements-dev.txt

FROM deps AS test
ENV PYTHONPATH=/src/src PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
COPY . .
CMD ["sh", "-c", "black --check src tests && pylint src && pylint --disable=missing-docstring,redefined-outer-name tests && pytest -p no:cacheprovider"]

FROM base AS runtime
COPY . /src
RUN pip install /src && rm -rf /src
ENTRYPOINT ["virtuous-cycles"]
