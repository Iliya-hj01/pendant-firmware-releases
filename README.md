# Lilum Firmware Releases

Signed firmware images and the shared documents that describe them for Lilum elements (currently the Mandalum, nRF54L15).

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

Firmware images are GitHub release assets, tag `<element>-v<version>` (for example `mandalum-v1.0.0`), asset `lilum-<element>-firmware-v<version>.bin`. Verify the SHA-256 and size from the catalogue before use.

The legacy `manifest.json` (nama-pendant) and its `v1.0.0` to `v1.3.1` releases are kept for older app builds and are no longer updated.

## Publishing a release

Run `release_firmware.ps1` from the firmware repository (`Mandalum-nRF54-PCB`) with a clean, committed source tree. Do not edit this repository by hand during a release.

```powershell
# 1. Build, sign and check everything; publishes nothing. Test .pio\release\<asset>.bin on hardware.
.\release_firmware.ps1 -Version 1.1.0 -Notes "What changed" -DryRun

# 2. Rebuild, require the tested SHA-256, then upload and publish.
.\release_firmware.ps1 -Version 1.1.0 -Notes "What changed" -ApprovedBy "Name" -ConfirmSha256 <sha256 from step 1>
```

The release date is the day the script runs. The script stops at the first failed check:

1. Preflight: clean sources, release repository equal to `origin/main`, version new and higher than every published one, tag not taken, `gh` signed in.
2. Clean build, host tests, firmware tables export.
3. Sign, verify, and check the signing key against the bootloader and earlier releases.
4. Assemble the version document and catalogue in a staged copy, then check: BLE contract matches the firmware, published history is unchanged, a definition revision never changes content, full validation.
5. Owner approval of the exact image SHA-256.
6. Upload the release asset and compare the downloaded copy.
7. Publish the version document and shared documents, and verify the live files.
8. Publish the catalogue last, then verify every live URL, checksum, size and signature.

Shared documents (`element-registery.json`, `lilum-BLE-contract.json`, `lilum-firmware-definition.json`) are edited and reviewed beforehand; the release publishes them together with the first release that needs them. Earlier entries in them must stay byte-identical.

