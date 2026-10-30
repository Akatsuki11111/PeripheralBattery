# Changelog

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
