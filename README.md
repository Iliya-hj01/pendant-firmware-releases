# Pendant Firmware Releases

Signed firmware images for the Lilum pendant (Seeed XIAO nRF54L15).

## For the Android App

Check for updates by fetching:
```
https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/main/manifest.json
```

## Releasing a new version

Run the release script from the `trialV1-nordic` project:
```powershell
.\release_firmware.ps1 -Version "1.1.0" -Notes "Added new animations"
```

This will:
1. Build the firmware via PlatformIO
2. Sign it with the MCUboot key
3. Update `manifest.json`
4. Create a GitHub Release with the signed binary attached
