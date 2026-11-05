# Changelog

## v2.11.1 — 刷新间隔菜单修正
- 点击底栏刷新入口可稳定打开菜单，并保存 5/15/30/60 秒刷新间隔。

## v2.11.0 — 设备电量界面优化
- 主窗口收窄至 350，底部六项操作排成一行。以透明边缘绘制外框圆角。
- 恢复大品牌标识和小设备图标。电量条加粗到 20，按电量区间着色。“有线”与百分比同字号。
- 托盘按多个原生像素尺寸分别绘制，扩大设备轮廓和进度条在图标内的占比。
- 新增浅色、深色及跟随系统选项，主界面和桌面悬浮窗同步切换。

## v2.10.0 — desktop display and compact controls
- Continue from the M3 Lite baseline in v2.9.2; preserve PR #1 and its protocol model gate.
- Add transparent desktop battery rows, detailed/compact modes, three sizes, drag/lock, and persisted position.
- Use a 400-DIP flyout, title version, two aligned footer rows and direct wired/battery selectors on uncertain USB devices.
- Check metadata at startup and every two hours; bound background reads, avoid automatic downloads and retry bursts.
- Reclaim owned stale caches and completed staging copies without deleting configuration, histories or device mappings.
- 305 regression tests pass.

## v2.9.2 — M3 Lite baseline release
- Read the VK M3 series battery over the same identity page the official Windows driver uses: interface 2 (`usage 0x0001:0x0000`, 33-byte output / 32-byte input reports, no Feature report declared) answers command `0x10`, where byte 13 is the percentage and byte 14 the link flag. The 2.4G receiver `249A:5C2F` (XCTECH, `Wireless-Receiver`) now routes to the `valkyrie_m220` backend instead of showing an unknown brand.
- Gate every reading on the model code inside that reply: `M220` = VK M3 Lite is checked against a capture from this machine plus three independent published captures at 78 %, 90 % and 100 %, while the shared `E023` (VK M3) code stays identify-only. Only the read command is ever sent, never a configuration write.
- State the remaining limits instead of papering over them: the receiver answers `0x10` by itself while the mouse sleeps, so a percentage is treated as live only when the link byte is `1` (otherwise the tray shows 连接待确认 and no stale value is presented as current), and the unverified status byte is never read as charging.
- Add `tests/test_valkyrie_m220.py` (real reply bytes, checksum rule, rejected/corrupted frames, the model-code gate, probe-level display) and `tests/test_m3lite_identification.py` (catalog routing and no brand for an adjacent unverified product ID). Identification comes from this machine plus the vendor driver's own device table, not the vkhub catalog, so `assets/valkyrie-devices.json` is left unchanged.

## v2.9.1 (unified release)
- Move the renamed battery-test entry to the update row: 无法适配电量时，点此测试.
- Automatically check once per primary application startup, with no automatic download or configuration dialog.
- Show a blue update badge when a new version is available; show three concise local release notes after successful installation, with persistent dismissal.
- Retain the unified read-only test/observation workflow and private external deployment configuration.
- 276 regression tests pass, including update badges and post-install notice behavior.

## v2.9.0 (unified release)
- Merge stable/experimental editions into one release, with one battery-test entry left of startup controls and no edition selector.
- Combine read-only precheck, paired unplug/plug samples, background observation and candidate review in one modeless, scrollable panel.
- Prioritize existing validated battery backends; stop when no usable reply exists. Only suitable unknown reports proceed to 1–2 hour observation.
- Require explicit unplug confirmation for unknown reports; exclude failed samples from elapsed usage and break continuity across gaps.
- Keep candidate rejection across reopening, require per-candidate confirmation, and allow old inferred mappings to be disabled without repeating observation.
- Preserve per-user update configuration, request authentication and signed-binary verification. Public artifacts contain no private deployment information.
- 272 regression tests pass. Observations remain local and correlations remain explicitly tentative.

## v2.8.3-experimental.1 (experimental)
- Share all privacy/window fixes and preserve battery research. Keep numeric management versions separate from the experimental build label.

## v2.8.2 (stable)
- Complete the v2.8 privacy and window fixes with strict major.minor.patch management versions and separately supplied release channels.
- Keep binary signature identity and experimental SemVer comparisons consistent without duplicating channel names in generated filenames.
- 259 regression tests pass; static archive privacy inspection and native Windows verification pass.

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
