# Contributing

Bug reports, installation feedback and improvement suggestions are welcome in
[GitHub Issues](https://github.com/except179/danfoss-link-haos/issues/new/choose).
Use the appropriate template; include versions, controller/firmware if known,
safe reproduction steps and expected/actual behavior. Keep reports free of
credentials, certificates, pairing state, backups and household/network data.
Follow [SECURITY.md](SECURITY.md) for vulnerabilities.

For code contributions, describe the user-visible problem and resulting
behavior, relevant validation and compatibility/rollback implications. Tests
must use synthetic controllers and temporary state; container checks use
network none. Never test a contribution against someone else's heating.
Do not introduce automatic pairing, insecure TLS fallback, uncertain-write
retries or persisted Heating Control ON.

Keep the physical device name **Danfoss Link CC**, original branding sources,
Leif Neland's MIT notice and all third-party attribution. Changes are contributed
under the project's MIT license; third-party material retains its terms.
See [developer notes](docs/DEVELOPMENT.md).

Maintainer: **Povilas Kucinskas (P.K. Except)** · [povilas.dk](https://povilas.dk).
