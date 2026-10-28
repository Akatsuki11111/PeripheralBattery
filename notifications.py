"""Group low-battery notifications and discard alerts for removed devices."""


def collect_low_alerts(devices, alerts, threshold, enabled=True):
    alerts.intersection_update(d.key for d in devices if d.present)
    newly_low=[]
    for d in devices:
        if d.charging or d.usable and d.percent>threshold+5:alerts.discard(d.key)
        if enabled and d.usable and d.percent<=threshold and not d.charging and d.key not in alerts:
            alerts.add(d.key);newly_low.append(d)
    return newly_low
