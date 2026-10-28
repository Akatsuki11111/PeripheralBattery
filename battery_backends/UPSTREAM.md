# Protocol providers

Source: https://github.com/HeyOkay/HaloBattery

Revision: `2251f0534a8e886c9692ead42056059b4f69d8c0`

License: MIT (LICENSE in this directory).

Selected read-only status providers are reused. Upstream GUI, updater, network features and auto-start are not included. Device access is sandboxed in separately terminable local worker processes by this application. `hidlist.enumerate` is supplied with one already enumerated physical device group at a time, preventing one device from hiding another.

Local change in `razer.py`: a confirmed receiver timeout (status 0x04) yields an explicit offline record even when there is no prior cached reading. Historical values are kept separately by the application and never counted as live battery.
