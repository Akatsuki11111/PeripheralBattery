# Changelog

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
