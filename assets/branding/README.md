# Original App branding — 2026-10-23

Original artwork for **Danfoss Link for HAOS**, by **Povilas Kucinskas
(P.K. Except)**, [https://povilas.dk](https://povilas.dk). Released under the
project's [MIT license](../../LICENSE). The house outline, thermostat and
wireless arcs were constructed as new vector geometry for this project;
no Danfoss or Home Assistant logo, reference graphic or external image was used.
Product names identify compatibility and do not imply endorsement.

| Delivery | Source | Specification |
| --- | --- | --- |
| [icon.png](../../danfoss_link/icon.png) | [icon.svg](icon.svg) | 128×128, square, RGBA PNG; transparent rounded outer corners; no tiny text |
| [logo.png](../../danfoss_link/logo.png) | [logo.svg](logo.svg) | 250×100, RGBA PNG; title “Danfoss Link for HAOS”, byline “by P.K. Except” |

The dark blue panel uses the Ingress palette with cyan house/connectivity
strokes, a pale thermostat outline and a subtle warm orange indicator.
The opaque panel behind lettering preserves contrast on both light and dark
pages; surrounding pixels remain transparent. DejaVu Sans supplies rasterized
lettering; no font file is bundled. Original SVG sources contain editable text.

## Reproduction and validation

```sh
python3 assets/branding/render.py
python3 assets/branding/verify.py
```

Rendering uses installed librsvg/Cairo and DejaVu Sans, with no network access,
downloaded graphics or added runtime dependency. Different renderer/font
versions can change raster bytes; dimensions, appearance and metadata must be
rechecked after regeneration. Verification checks PNG signatures, every chunk
CRC, exact dimensions, RGBA depth, decompressed pixels, transparent corners,
opaque interior, antialiased edges and absence of EXIF/text/time metadata.

Both native-size PNGs and reduced icon previews on light/dark surfaces were
visually inspected locally. The title/byline remain readable at the native
logo size, and the house/thermostat/wireless silhouette is identifiable at
small icon sizes. Installed HAOS display is still pending. There are no
household screenshots, private image metadata or embedded external resources.

## Supervisor packaging and display

The PNGs belong at the App folder root, alongside `config.yaml`. The official
[App file reference](https://contributors.home-assistant.io/apps/reference/files/)
identifies them as Supervisor repository assets; the
[presentation guide](https://contributors.home-assistant.io/apps/guides/presentation/)
recommends 128×128 and approximately 250×100. The Docker context intentionally
excludes these files: Supervisor reads them from App source, and the runtime
does not need copies in the image. Both PNGs and editable sources must be
tracked and included in public source archives; the checkpoint verifies that
with a local Git source archive. Public source archives include both PNGs and editable sources.

After a repository/source update, reload the App Store so
Supervisor fetches the new source metadata, then refresh the browser if an
asset is cached. No heating process restart is inherently needed for these
repository images. An installed local App may continue showing its old source
copy until that copy is updated through an approved route; a store reload
cannot transfer files that are absent. Confirm behavior on the installed
Supervisor before promising refresh-only behavior. A future versioned release
can carry the assets with other approved changes; the artwork ships with this v0.3.1 preview; no production deployment is performed by publication.

The original Leif Neland bridge attribution remains in App documentation and
the existing Ingress footer. Branding does not alter MQTT device identity,
pairing, credentials, topics, heating logic or the Ingress UI.
