# syntax=docker/dockerfile:1
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS toolchain
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl g++ jq xz-utils \
    && rm -rf /var/lib/apt/lists/*

FROM toolchain AS infer
ARG INFER_VERSION=v1.3.0
ARG INFER_SHA256=02be62ba931cb43e2d42bbf7abf4bd9a410cf8464cce5453934e25c90a825850
RUN curl -fsSL -o /tmp/infer.tar.xz "https://github.com/facebook/infer/releases/download/${INFER_VERSION}/infer-linux-x86_64-${INFER_VERSION}.tar.xz" \
    && echo "${INFER_SHA256}  /tmp/infer.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/infer.tar.xz -C /opt && rm /tmp/infer.tar.xz \
    && ln -s "/opt/infer-linux-x86_64-${INFER_VERSION}/bin/infer" /usr/local/bin/infer

FROM infer AS report
ENV LANG=C.UTF-8
WORKDIR /work
COPY example.cpp .
RUN infer --cost-only -o infer-out -- g++ -c example.cpp \
    && infer debug -o infer-out --procedures --procedures-name --procedures-callees --select all > procs.txt \
    && cp infer-out/costs-report.json .

FROM scratch AS fixture
COPY --from=report /work/costs-report.json /work/procs.txt /

FROM toolchain AS check
COPY --from=report /work/costs-report.json /work/procs.txt /fresh/
COPY costs-report.json procs.txt /committed/
RUN norm='map({procedure_id, procedure_name, loc: .loc.file, degree: .exec_cost.degree, hum: .exec_cost.hum}) | sort_by(.procedure_id, .hum.hum_polynomial)' \
    && diff <(jq -S "$norm" /committed/costs-report.json) <(jq -S "$norm" /fresh/costs-report.json) \
    && diff /committed/procs.txt /fresh/procs.txt
