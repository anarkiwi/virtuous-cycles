# syntax=docker/dockerfile:1
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS toolchain
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl g++ jq xz-utils \
    && rm -rf /var/lib/apt/lists/*

FROM toolchain AS infer
ARG INFER_VERSION=v1.3.0
RUN curl -fsSL "https://github.com/facebook/infer/releases/download/${INFER_VERSION}/infer-linux-x86_64-${INFER_VERSION}.tar.xz" \
    | tar -xJ -C /opt \
    && ln -s "/opt/infer-linux-x86_64-${INFER_VERSION}/bin/infer" /usr/local/bin/infer

FROM infer AS report
ENV LANG=C.UTF-8
WORKDIR /work
COPY example.cpp .
RUN infer --cost-only -o infer-out -- g++ -c example.cpp

FROM scratch AS fixture
COPY --from=report /work/infer-out/costs-report.json /

FROM toolchain AS check
COPY --from=report /work/infer-out/costs-report.json /fresh.json
COPY costs-report.json /committed.json
RUN norm='map({procedure_id, procedure_name, loc: .loc.file, degree: .exec_cost.degree, hum: .exec_cost.hum}) | sort_by(.procedure_id, .hum.hum_polynomial)' \
    && diff <(jq -S "$norm" /committed.json) <(jq -S "$norm" /fresh.json)
