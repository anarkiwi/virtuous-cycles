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

# vc-cxx-cost (cxx-cost/): clang 20 from Ubuntu 24.04, so the binary also runs
# in any Ubuntu 24.04 image that installs the `cxx-base` packages.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS cxx-base
ARG LLVM_VERSION=1:20.1.2-0ubuntu1~24.04.3
RUN apt-get update && apt-get install -y --no-install-recommends \
      libclang-cpp20=${LLVM_VERSION} libllvm20=${LLVM_VERSION} \
      libclang-common-20-dev=${LLVM_VERSION} libstdc++-14-dev libc6-dev \
    && rm -rf /var/lib/apt/lists/*

FROM cxx-base AS cxx-toolchain
ARG LLVM_VERSION=1:20.1.2-0ubuntu1~24.04.3
RUN apt-get update && apt-get install -y --no-install-recommends \
      clang-20=${LLVM_VERSION} libclang-20-dev=${LLVM_VERSION} \
      llvm-20-dev=${LLVM_VERSION} llvm-20-tools=${LLVM_VERSION} \
      clang-format-20=${LLVM_VERSION} libclang-rt-20-dev=${LLVM_VERSION} \
      cmake ninja-build python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
ENV CC=clang-20 CXX=clang++-20 PATH=/usr/lib/llvm-20/bin:${PATH}

FROM cxx-toolchain AS cxx-build
COPY cxx-cost/CMakeLists.txt /src/
COPY cxx-cost/include /src/include
COPY cxx-cost/src /src/src
RUN cmake -S /src -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH=/usr/lib/llvm-20 && cmake --build /build \
    && cmake --install /build --prefix /usr/lib/llvm-20

FROM cxx-toolchain AS cxx-test
COPY cxx-cost/CMakeLists.txt /src/cxx-cost/
COPY cxx-cost/include /src/cxx-cost/include
COPY cxx-cost/src /src/cxx-cost/src
RUN cmake -S /src/cxx-cost -B /cov -G Ninja -DCMAKE_BUILD_TYPE=Debug \
      -DVC_COVERAGE=ON -DCMAKE_PREFIX_PATH=/usr/lib/llvm-20 && cmake --build /cov
COPY . /src
RUN pip install --break-system-packages --no-cache-dir /src
WORKDIR /src/cxx-cost
CMD ["sh", "-c", "scripts/test /cov/vc-cxx-cost"]

FROM cxx-base AS cxx-runtime
COPY --from=cxx-build /usr/lib/llvm-20/bin/vc-cxx-cost /usr/lib/llvm-20/bin/
COPY --from=cxx-build /usr/lib/llvm-20/include/vc /usr/local/include/vc
RUN ln -s /usr/lib/llvm-20/bin/vc-cxx-cost /usr/local/bin/vc-cxx-cost
ENTRYPOINT ["vc-cxx-cost"]
