# syntax=docker/dockerfile:1.2
FROM alpine/git as enterprise

ARG ODOO_ENTERPRISE_REPOSITORY
ARG GITHUB_TOKEN
ARG ODOO_VERSION

RUN if [[ -n "${ODOO_ENTERPRISE_REPOSITORY}" ]] ; then \
      git clone --branch ${ODOO_VERSION} --single-branch --depth 1 https://${GITHUB_TOKEN}@github.com/${ODOO_ENTERPRISE_REPOSITORY} /enterprise; \
    else \
      echo "ODOO_ENTERPRISE_REPOSITORY is empty; skipping clone."; \
      mkdir -p /enterprise; \
    fi




FROM ghcr.io/adomi-io/odoo:18.0
USER root

RUN apt-get update && \
    apt-get install -y git openssh-client rsync && \
    rm -rf /var/lib/apt/lists/*

COPY requirements*.txt .
RUN pip install -r requirements.txt

ARG PYTHON_VERSION
RUN pip install --target=/opt/odoo-upgrade git+https://github.com/odoo/upgrade-util
RUN echo "/odoo" > /venv/lib/python${PYTHON_VERSION}/site-packages/odoo_local.pth \
    && echo "/volume/enterprise" > /venv/lib/python${PYTHON_VERSION}/site-packages/odoo_enterprise.pth \
    && echo "/opt/odoo-upgrade" > /venv/lib/python${PYTHON_VERSION}/site-packages/upgrade_utils.pth


ARG DEV_MODE
RUN if [[ "$DEV_MODE" = "true" ]]; then pip install -r requirements-dev.txt; fi

USER ubuntu

COPY docker/config/odoo.conf /volumes/config/odoo.conf
COPY docker/scripts /volumes/scripts
COPY addons /volumes/addons

COPY --from=enterprise /enterprise /volumes/enterprise

