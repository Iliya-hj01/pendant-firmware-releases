# MTU23 positive-path lab catalogue

**Partial lab publication only, not a fully validated firmware bundle.**
Production on `main` is unchanged. This publication contains only the
validated MTU23 OTA-GOOD catalogue and its complete dependency set.

## Configure this catalogue

<https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/app-team-lab-20261022-v1/header-fixed-v1/catalogues/mtu23/good/lilum-firmware-catalogue.json>

- Catalogue revision: `2026102401`.
- Offers exactly OTA-BASE `1.90.0` and OTA-GOOD `1.90.1`.
- Product code `1`, hardware revision `1`, BLE protocol `1.0`.
- Start from the matching corrected OTA-BASE and isolated lab bootloader.

```text
-PlilumDebugCatalogueUrl=https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/app-team-lab-20261022-v1/header-fixed-v1/catalogues/mtu23/good/lilum-firmware-catalogue.json
```

Inspect the authorized debug app's actual cached catalogue revision and
offered target before accepting the test. The configured ATT MTU ceiling
of `23` is not a measurement of negotiated ATT MTU.

## Complete published dependency set

The seven prepared source files below are published byte-for-byte unchanged:

- [MTU23 good catalogue](catalogues/mtu23/good/lilum-firmware-catalogue.json).
- [OTA-BASE 1.90.0 document](firmwares/mandalum/lilum-mandalum-firmware-v1.90.0.json).
- [OTA-GOOD 1.90.1 document](firmwares/mandalum/lilum-mandalum-firmware-v1.90.1.json).
- [OTA-BASE signed image](images/mandalum-app-ota-base-mtu23-1.90.0.signed.bin).
- [OTA-GOOD signed image](images/mandalum-app-ota-good-mtu23-1.90.1.signed.bin).
- [Element registry](shared/element-registery.json).
- [BLE contract](shared/lilum-BLE-contract.json).

[Publication inventory and validation scope](mtu23-good-publication.json)
records exact hashes, byte counts and immutable source-manifest pins.
The full original staging manifest is not published as a partial manifest:
it describes other files outside this limited upload.

## Held and unpublished

The two REACTIVE `.31` firmware documents and both catalogues that reference
them are withheld. Their names `lab.music.synthetic` and
`lab.movement.synthetic` fail the published schema's animation-name pattern
`^[a-z][a-z0-9_]*$`. This is a metadata defect, not an intentional negative
fixture. Original files, manifests and exact validation failures are retained.

Repair requires correcting the metadata/generator without changing animation
IDs or behavior, regenerating internal and file hashes, sizes, catalogue
references and manifests, and validating the complete corrected chain.
Do not weaken the schema, patch bytes while uploading, reuse changed
published document identities, or publish dangling references.
REACTIVE remains blocked for full regression sign-off.

No other lab case is claimed published or validated by this partial upload.
OTA-FAIL `.2` is a valid signed, deliberately non-confirming trial, not a
malformed fixture; it is not offered here. No private keys, protected backups,
programmer logs, unsigned work inputs or recovery bundles are published.
Publication does not prove app-cache acceptance, OTA success, rollback,
negotiated MTU or hardware qualification. No hardware operation is performed.
