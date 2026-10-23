# Public source inventories

`vendor-sha256.json` identifies the 57 unchanged upstream source files included
with this App. It contains file hashes, not household identity or CA fingerprints.
Run `python3 scripts/verify_source.py` to compare them.

`source-sha256.json` identifies the public snapshot files except itself. Run
`python3 scripts/verify_public.py` for the bounded privacy, syntax, link and
inventory preflight. Update the inventory deliberately when changing source;
it is a checksum record, not a signature, full audit or proof of installed safety.

Distribution is via Supervisor's included Dockerfile build for amd64. There is
no project GHCR image. The upstream base is pinned by digest in the Dockerfile;
its public service CA bundle is distinct from each user's private broker trust.
Private development history, household configuration and raw validation reports
are not included in this clean public history.
