# No native compilation or mutable dependency resolution on the NUC.
# This digest contains the audited private OpenSSL patch and paho-mqtt 2.1.0.
FROM ghcr.io/leifnel/danfoss-link-mqtt@sha256:cc94fa1351ba142d4f04df35d127216ba8364639a0c10c9a86361568711e1a04
ARG BUILD_VERSION=0.3.1
ARG BUILD_ARCH=amd64
ARG BUILD_REVISION=local-unreleased
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.title="Danfoss Link for HAOS — by P.K. Except" \
      org.opencontainers.image.authors="Povilas Kucinskas (P.K. Except), https://povilas.dk (HAOS App packaging); Leif Neland (original MQTT bridge)" \
      org.opencontainers.image.vendor="Povilas Kucinskas (P.K. Except)" \
      org.opencontainers.image.licenses="MIT" \
      maintainer="Povilas Kucinskas (P.K. Except), https://povilas.dk" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.source="https://github.com/except179/danfoss-link-haos" \
      org.opencontainers.image.base.digest="sha256:cc94fa1351ba142d4f04df35d127216ba8364639a0c10c9a86361568711e1a04" \
      org.opencontainers.image.description="Unofficial community project. Not affiliated with or endorsed by Danfoss. HAOS packaging by Povilas Kucinskas (P.K. Except); original MQTT bridge by Leif Neland (02d69aa)."
USER root
COPY vendor/src/ /app/
COPY vendor/tests/ /app/tests/
COPY vendor/LICENSE vendor/THIRD_PARTY_NOTICES.md /opt/notices/
COPY vendor/patches/ /opt/notices/patches/
COPY rootfs/ /opt/haos_app/
ENV PYTHONPATH=/opt/haos_app:/app:/app/tests
ENV DANFOSS_ALLOW_WRITES=false MQTT_TLS=true
RUN test "$BUILD_ARCH" = amd64 && python /opt/haos_app/runtime_check.py \
    && chmod -R a-w /opt/haos_app /app
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/opt/haos_app/healthcheck.py"]
# Short root bootstrap prepares ONLY this App's /data; networking runs as nobody.
ENTRYPOINT ["python", "/opt/haos_app/bootstrap.py"]
CMD []
