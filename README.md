# Lilum Firmware Releases

Signed firmware images and shared documents for Lilum elements, including the Mandalum and Spirilum. The catalogue is authoritative for which product versions have actually been released.

Everything here is append-only: a published version is never edited or deleted. A mistake is fixed by publishing a new version, and a bad release is withdrawn in the catalogue with a reason.

## For the app

Start from the catalogue. It lists every release, and records the URL, SHA-256 and size of every other document and image it refers to:

```
https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/main/lilum-firmware-catalogue.json
```

| File | Content |
| --- | --- |
| `lilum-firmware-catalogue.json` | Entry point. Releases per element, their status, `catalogRevision` (only ever increases), checksums of the shared documents. |
| `element-registery.json` | Registered elements and hardware revisions. |
| `lilum-BLE-contract.json` | BLE configuration protocol, one entry per protocol version. |
| `lilum-firmware-definition.json` | JSON schemas for the firmware documents, one entry per schema version. |
| `firmwares/<element>/lilum-<element>-firmware-v<version>.json` | One release: settings, animations, palettes, defaults, compatibility, artifact URL and checksum. |

Firmware-document schema version 2 requires
`definition.publicationAnimationIds`, a stable-slug-to-animation-ID mapping.
An empty object explicitly disables playlist publication/conversion. The
release tool selects the highest published schema version and validates that
every mapped ID exists in that firmware document's animation list. Adding a
future schema version requires updating and testing the release generator and
validator before using it for a firmware release.

Firmware images are GitHub release assets, tag `<element>-v<version>` (for example `mandalum-v1.0.0`), asset `lilum-<element>-firmware-v<version>.bin`. Verify the SHA-256 and size from the catalogue before use.

The legacy `manifest.json` (nama-pendant) and its `v1.0.0` to `v1.3.1` releases are kept for older app builds and are no longer updated.

## Playlists

Published playlists have a separate entry point:

```
https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/main/playlists/index-v1.json
```

The index records each publication's status, target, relative document path,
byte size and SHA-256. Verify the document size and checksum before uploading
the complete playlist to an element. Targets pin the product, hardware
revisions, firmware version, definition revision and firmware-document SHA-256.
Compute `sizeBytes` and `sha256` from the exact Git blob bytes, not a
CRLF-converted working-tree copy.
Animation IDs are stable slugs from `definition.publicationAnimationIds`;
each entry supplies all eight parameter bytes. `durationSeconds` is shared
by every entry.

[Mandalum Defaults](playlists/mandalum-defaults/r1.json) targets Mandalum
hardware revision 1, firmware 1.0.8 and definition revision 6. It contains
Rainbow Cycle, Palette Cycle, Confetti, Vortex, Portal and Wings, in that
order, using their published factory parameter defaults and 10 seconds per
entry (a 60-second cycle).

Playlist publications are immutable. Publish corrections under a new
`publicationRevision` and `r<revision>.json` path, preserve existing
publications and migrations, and increment `indexRevision` when updating
the index. Playlist publication does not modify the firmware catalogue.

### Test publications

- [Mandalum Defaults, revision 2](playlists/mandalum-defaults/r2.json)
  targets firmware 1.0.8 / definition 6. Rainbow Cycle speed changes from
  60 to 90 and spread from 30 to 45. The other 46 parameter bytes, entry
  order and 10-second duration are unchanged from revision 1.
- [Mandalum Defaults (1.0.7), revision 1](playlists/mandalum-defaults-v1-0-7/r1.json)
  targets firmware 1.0.7 / definition 5, with the original six animations,
  all 48 factory-default parameter bytes and 10 seconds per entry.
- [Mandalum 1.0.7 to 1.0.8 migration, revision 3](playlists/migrations/mandalum-1-0-7-to-1-0-8/r3.json)
  maps all ten source animation slugs to themselves and preserves every
  parameter byte and playlist duration. Migration revision 2 is withdrawn
  because its indexed size and checksum do not match its published Git blob.

### Version 1 data contract

[schema-v1.json](playlists/schema-v1.json) is the JSON Schema 2020-12
contract for playlist documents, the index and migration documents.
This defines release data; app-side migration support must implement
the following semantic checks in addition to JSON Schema validation.

A playlist publication is identified by `(playlistId, publicationRevision)`,
not `playlistId` alone. Index rows for revisions 1 and 2 coexist; history
is not overwritten. Match the exact target and available status before
selecting the highest publication revision for a playlist ID. Migration
publications likewise use `(migrationId, publicationRevision)`. Each
identity must appear only once, and its path must match the ID and revision.
Withdrawn index rows require a nonempty `withdrawalReason`; the immutable
documents and their earlier revisions remain in place.

A migration index row records `migrationId`, `publicationRevision`,
`status`, `name`, optional `description`, full `source` and `target`
fingerprints, `path`, `sizeBytes` and `sha256`. Verify the downloaded
bytes and match its metadata to the index before using the document.
Both fingerprints must match available firmware catalogue documents,
including their SHA-256, product, hardware revisions and definition revision.

Migration documents use `documentType: "lilum-playlist-migration"` and
`formatVersion: 1`. `animationMappings` contains `sourceAnimationId` and
`targetAnimationId` stable slugs, with exactly one mapping per source slug.
Every source and destination slug must exist in its respective firmware
definition. A listed migration is directional; never infer a reverse map.

Version 1 supports only `parameterPolicy: "preserve"` and
`durationPolicy: "preserve"`: preserve all eight parameter bytes, entry
IDs, labels, entry order and the shared duration, and change only mapped
animation slugs and the target. Validate parameters against both firmware
definitions, including ranges and list options, and validate the duration
against both firmware settings. Entry IDs must be unique within a playlist.
Reject the entire operation on an unmapped slug, ambiguous mapping,
fingerprint mismatch or invalid value; never skip, clamp, default or
partially apply entries.

The result is unpublished local/device playlist data, not a newly published
playlist identity. This migration does not adopt revision 2 parameters or
redirect the 1.0.7 playlist ID to `mandalum-defaults`. Its parameters stay
at the source values even though the target firmware becomes 1.0.8.

Published schema versions are immutable; incompatible future contracts
must use a new schema and format version. Firmware catalogue documents
are not modified by playlist or migration publication.

## Publishing a release

Run `release_firmware.ps1` from the firmware repository (`Mandalum-nRF54-PCB`) with a clean, committed source tree. Do not edit this repository by hand during a release.

```powershell
# 1. Build, sign and check everything; publishes nothing. Test .pio\release\<asset>.bin on hardware.
.\release_firmware.ps1 -Element mandalum -Version 1.1.0 -Notes "What changed" -ApprovedBy "Name" -DryRun

# 2. Rebuild, require the tested SHA-256, then upload and publish.
.\release_firmware.ps1 -Element mandalum -Version 1.1.0 -Notes "What changed" -ApprovedBy "Name" -ConfirmSha256 <sha256 from step 1>

# Spirilum has an independent version history and may use the same version number.
.\release_firmware.ps1 -Element spirilum -Version 1.0.0 -Notes "First Spirilum release" -ApprovedBy "Name" -DryRun
```

The release date is the day the script runs. The script stops at the first failed check:

1. Preflight: clean sources, release repository equal to `origin/main`, version new and higher than every published version of the selected product (versions may match across products), tag not taken, `gh` signed in.
2. Clean build, host tests, firmware tables export.
3. Sign, verify, and check the signing key against the bootloader and earlier releases.
4. Assemble the version document and catalogue in a staged copy, then check: BLE contract matches the firmware, published history is unchanged, a definition revision never changes content, full validation.
5. Owner approval of the exact image SHA-256.
6. Upload the release asset and compare the downloaded copy.
7. Publish the version document and shared documents, and verify the live files.
8. Publish the catalogue last, then verify every live URL, checksum, size and signature.

Shared documents (`element-registery.json`, `lilum-BLE-contract.json`, `lilum-firmware-definition.json`, `README.md`) are edited and reviewed beforehand; the release publishes them together with the first release that needs them. Earlier entries in them must stay byte-identical.
