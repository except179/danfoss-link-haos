#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 scripts/test_offline.py
python3 scripts/verify_source.py
revision=$(git rev-parse HEAD)
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  revision="${revision}-dirty"
fi
docker build --platform linux/amd64 --network none \
  --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.3.1 \
  --build-arg "BUILD_REVISION=$revision" \
  --build-arg SOURCE_DATE_EPOCH=1792369546 \
  -t danfoss-link-haos:0.3.1 danfoss_link
# All credentials/certificates here are newly generated synthetic fixtures.
# No production state mounts, LAN connections or broker restart.
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 65534:65534 --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --mount "type=bind,src=$(pwd)/tests,dst=/verification,readonly" \
  --mount "type=bind,src=$(pwd)/danfoss_link/config.yaml,dst=/verification-config.yaml,readonly" \
  -e PYTHONPATH=/opt/haos_app:/app:/app/tests:/verification \
  --entrypoint python danfoss-link-haos:0.3.1 -m unittest \
  test_native_tls test_pace_crypto test_mqtt_status test_mqtt_tls_wire test_ingress test_pairing_lifecycle test_ingress_wire test_first_install test_heating
# Exercise only the bootstrap's real CHOWN/SETUID/SETGID requirements.
docker run --rm --network none --read-only --cap-drop ALL --cap-add CHOWN --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges --user 0:0 \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m,mode=1777 \
  --mount "type=bind,src=$(pwd)/tests,dst=/verification,readonly" \
  -e PYTHONPATH=/opt/haos_app:/app:/app/tests:/verification \
  --entrypoint python danfoss-link-haos:0.3.1 -m unittest test_bootstrap_container
mkdir -p dist/0.3.1
docker image inspect danfoss-link-haos:0.3.1 > dist/0.3.1/image-inspect.json
docker save -o dist/0.3.1/danfoss-link-haos-0.3.1-amd64.tar danfoss-link-haos:0.3.1
sha256sum dist/0.3.1/danfoss-link-haos-0.3.1-amd64.tar > dist/0.3.1/image-archive.sha256
printf '%s\n' 'Image built and container tests passed. Supervisor, real MQTT and backup gates still required.'
