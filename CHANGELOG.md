# Changelog

## v2.8.1-experimental.1 (experimental)
- Retain battery research/long observations, with the same privacy, update-integrity and window fixes as stable v2.8.0.

## v2.8.0 (stable)
- Remove deployment-specific information from public artifacts and require optional per-user protected update configuration.
- Authenticate update requests and verify signed executable content before installation; keep release notes readable.
- Validate version numbers separately from software names; use a fixed upload filename.
- Avoid persistent mouse focus outlines on tool buttons while keeping keyboard focus hints.
- Launch all background workers with explicit hidden/no-console flags and preserve stable popup geometry during refresh.
- 258 regression tests pass. Historical affected attachments have been withdrawn; use this privacy-corrected version.

## v2.7.1-experimental.1 (experimental)
- Retain guided battery research and long observations; share all controller improvements from stable v2.7.0.
- Keep experimental mappings separate from trusted readings; no new claim that unknown protocols can be inferred automatically.

## v2.7.0 (stable)
- Enumerate both Windows RawGameController and Gamepad, including native GIP/wireless-adapter controllers absent from hidapi.
- Add Xbox One/S/Series/Elite/Adaptive USB/Bluetooth/BLE identities and conservative model-family matching.
- Add current-connected Bluetooth PnP/AEP battery properties and independently decoded Xbox report 0x04, with read-only input-report fallback.
- Preserve XInput/Bluetooth grades as grades; show segmented bars and legible tray glyphs without invented percentages.
- Cache last valid grade and timestamp during sleep; do not persist battery across anonymous XInput slot reassignment.
- Route equal-model native controllers by opaque ID hashes, never list order; reject missing identities and synthetic full-capacity reports.
- 244 regression tests pass. No physical Xbox hardware was available; different firmware/transport combinations still require hardware validation.
- Stable continues to omit all battery experiment/observation runtime modules; signed server-only update policy is unchanged.

## v2.6.1-experimental.1 (experimental)
- Keep guided adaptation/long observations and prioritize verified device-specific status protocols.
- End immediately when validated battery data is found; skip declared padding-only Feature reports and stop when no usable channel exists.
- Share M5 Lite support and signed VersionHub updates with stable v2.6.0.


## v2.6.0 (stable)
- Adapt VK M5 Lite through official RY F7 battery/status plus 8F model identity; do not infer brand from shared receiver VID/PID.
- Reject offline receiver battery cache and official USB fixed-100 placeholder; preserve last valid timestamp and clear cache on model changes.
- Move all in-app update checks/downloads to VersionHub; bind releases with pinned RSA-2048 signatures and SHA256, with no GitHub fallback or management credentials.
- Add signed server publishing tools; preserve previous server/GitHub versions.
- Keep approximately 28.6 MB standalone runtime without further forced size cuts.
- 218 regression tests pass, including real native signature verification.


## v2.5.1-experimental.1 (experimental)
- Retain guided battery adaptation, long observations and locally confirmed experimental mappings.
- Share v2.5.0 controller support, sleep timestamps and trimmed runtime.
- This pre-release has its own SemVer tag and executable; stable v2.5.0 omits experiment modules.


## v2.5.0 (stable)
- Show the timestamp of the last valid battery reading directly on sleeping/unconfirmed device cards.
- Add 22 controller brands, 539 controller IDs, gamepad glyphs and safe composite-node consolidation.
- Add XInput grades, Windows BatteryReport and passive battery parsing for selected Sony/Nintendo/8BitDo models. Reject ambiguous matching and synthetic wired/full reports.
- Exclude all guided battery experiments, long observations and learned mapping runtime modules from the stable EXE. Preserve identity/descriptor diagnostics.
- Trim unused Qt components: approximately 28.6 MB instead of 48.75 MB.
- 173 regression tests pass; both frozen variants have independent startup, module, worker, native UI and HTTPS checks.
- KP50B/Rainbow2 identification is verified; their exact private battery queries remain unsupported.


## v2.4.1 (experimental)
- Arrange startup, refresh interval, release channel and version/update controls into two compact rows.
- Keep full startup status in tooltips; show query errors only when present.
- Keep download progress visible when reopening the flyout.
- 154 regression tests pass; real installed v2.4.0 to v2.4.1 GitHub download, cancellation, verified replacement and restart passed; preferences and startup preserved.


## v2.4.0 (experimental)
- Add current version and stable/experimental GitHub Release checks.
- Add in-app download progress and cancellation, SHA256 verification, restart installation and rollback backups.
- Preserve application preferences and the fixed startup executable.
- 154 regression tests pass; old versions require a one-time manual upgrade.


## v2.3.1 (experimental)
- Add 35 exact Valkyrie model identifiers from the official VK HUB catalog; exclude shared OEM IDs from unconditional brand recognition.
- Prefer known catalog model names over generic USB receiver strings.
- Distinguish absent Feature reports, oversized reports, access failures and failed reads; retain Windows error codes.
- Export privacy-limited HID identity and descriptor diagnostics, including unknown receivers.
- 145 regression tests pass. No claim of battery support for the remote user's unverified mouse.

## v2.3.0 (experimental)
- Add bounded one/two-hour background observations and manually enabled experimental readings.
- Preserve timestamped last known mouse battery during inactivity; exclude cache from live minimum and alerts.
- Exclude known offline devices from the pending adaptation list.

## v2.2.0 (experimental)
- Add guided status-report sampling, differential evidence and cancellation.

## v2.1.2
- Expand USB keyboard identification and add Nova 5 direct USB charging reads.
