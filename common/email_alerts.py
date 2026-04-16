import time
import logging

logger = logging.getLogger(__name__)

_email_cooldown: dict = {}

ALERT_HTML_TEMPLATE = """
<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;background:#0a1628;color:#e0e0e0;padding:24px;border-radius:12px">
  <h1 style="color:#ef4444;margin-top:0">⚠️ CRITICAL Flood Alert</h1>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Alert Type</td><td style="padding:8px">{alert_type}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Station</td><td style="padding:8px">{station_id}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Severity</td><td style="padding:8px;color:#ef4444;font-weight:700">{severity}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Description</td><td style="padding:8px">{description}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Triggered Value</td><td style="padding:8px">{value}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Threshold</td><td style="padding:8px">{threshold}</td></tr>
    <tr><td style="padding:8px;color:#7dd3fc;font-weight:600">Timestamp</td><td style="padding:8px">{timestamp}</td></tr>
  </table>
  <p style="font-size:12px;color:#5a7a9b;margin-top:16px">AquaGuard Flood Early Warning System</p>
</div>
"""

ALERT_TEXT_TEMPLATE = (
    "CRITICAL FLOOD ALERT\n"
    "Alert: {alert_type}\n"
    "Station: {station_id}\n"
    "Severity: {severity}\n"
    "Description: {description}\n"
    "Value: {value} (threshold: {threshold})\n"
    "Time: {timestamp}"
)


def send_critical_email(
    ses_config: dict,
    station: str,
    alert_type: str,
    severity: str,
    description: str,
    value,
    threshold,
    timestamp: str,
    cooldown_sec: int = 60,
):
    if ses_config is None:
        return

    ses_client = ses_config["client"]
    from_addr = ses_config["sender"]
    to_addr = ses_config["recipient"]

    cooldown_key = f"{station}:{alert_type}"
    now = time.time()
    if cooldown_key in _email_cooldown and now - _email_cooldown[cooldown_key] < cooldown_sec:
        return
    _email_cooldown[cooldown_key] = now

    fmt_kwargs = dict(
        alert_type=alert_type.replace("_", " "),
        station_id=station,
        severity=severity,
        description=description,
        value=value,
        threshold=threshold,
        timestamp=timestamp,
    )
    subject = f"⚠️ CRITICAL FLOOD ALERT — {fmt_kwargs['alert_type']} at {station}"
    body_html = ALERT_HTML_TEMPLATE.format(**fmt_kwargs)
    body_text = ALERT_TEXT_TEMPLATE.format(**fmt_kwargs)

    try:
        ses_client.send_email(
            Source=from_addr,
            Destination={"ToAddresses": [to_addr]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        logger.info(f"SES email sent: {severity} {alert_type} @ {station}")
    except Exception as e:
        logger.warning(f"SES email failed: {e}")
