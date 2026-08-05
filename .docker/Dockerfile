FROM python:3.14-alpine

ARG DEVCTL_VERSION=0.0.0-dev

RUN apk add --no-cache docker-cli docker-cli-compose git make
RUN pip install --no-cache-dir --root-user-action=ignore ruff jsonschema rich prompt_toolkit

WORKDIR /opt/devctl

COPY bin/devctl /usr/local/bin/devctl
COPY src /opt/devctl/src

RUN chmod +x /usr/local/bin/devctl

ENV DEVCTL_STATE_DIR=/state \
    DEVCTL_REPO_ROOT=/opt/devctl \
    PYTHONPATH=/opt/devctl/src \
    DEVCTL_DNS_SUFFIX=localhost \
    DEVCTL_UPSTREAM_HOST=host.docker.internal \
    DEVCTL_PUBLISH_HOST=127.0.0.1 \
    DEVCTL_VERSION=${DEVCTL_VERSION}

ENTRYPOINT ["devctl"]
