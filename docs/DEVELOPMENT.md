# Developer notes

Users install through Supervisor; these commands are for contributors only.

```sh
python3 scripts/verify_public.py
python3 scripts/verify_source.py
python3 scripts/test_offline.py
sh scripts/build.sh
```

The build pins the upstream base digest, copies unchanged vendored source and
the HAOS adapter, then runs synthetic checks. Tests must never mount production
state or contact a real broker/CC. Container runs use `--network none`, read-only
roots, temporary synthetic state and bounded capabilities. Native TLS tests
need the project's pinned patched OpenSSL runtime; ordinary host Python is not
a substitute. Existing test sources remain available without private evidence.

`scripts/build.sh` exports only local `dist/0.3.1/` artifacts. It does not push,
publish, pair or control heating. Exports and generated identities stay ignored.
The included manual validation workflow cannot publish and is not automatically
run by this launch. No hosted workflow pass is claimed.

Public distribution uses Supervisor source builds; there is no project-owned
GHCR image. Dockerfile `BUILD_REVISION` can be set to a clean public commit by a
maintainer build; Supervisor source-build defaults do not prove that provenance.
The upstream pinned image supplies native dependencies and public service trust
anchors. Preserve [MIT](../LICENSE) and [third-party notices](../danfoss_link/vendor/THIRD_PARTY_NOTICES.md).
Full dependency/SBOM/vulnerability clearance remains open.

See [contribution rules](../CONTRIBUTING.md), [security](../SECURITY.md) and
[testing limits](TESTING.md). Do not add automatic pairing, insecure TLS fallback,
persisted ON or retries of uncertain physical writes.
