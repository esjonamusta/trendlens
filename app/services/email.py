"""SMTP email sender for digest reports."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_digest(to_email: str, first_name: str, topics: list[dict], domain: str, frequency: str) -> None:
    """Send a digest email to one user. Raises on failure."""
    if not _smtp_configured():
        log.warning("SMTP not configured — skipping digest email")
        return

    from_addr = settings.email_from or settings.smtp_user
    freq_label = "Weekly" if frequency == "weekly" else "Monthly"

    # Plain-text body
    lines = [
        f"Hi {first_name},",
        "",
        f"Here are your top trends for {domain} — {freq_label.lower()} digest.",
        "",
    ]
    for i, t in enumerate(topics[:3], 1):
        lines.append(f"{i}. {t.get('headline', '')}")
        if t.get("what_happened"):
            lines.append(f"   {t['what_happened']}")
        if t.get("pm_action"):
            lines.append(f"   → {t['pm_action']}")
        lines.append("")

    lines += [
        "View your full dashboard: http://localhost:8000/app",
        "",
        "— TrendLens",
        "Unsubscribe: visit your profile settings and set Email digest to Off.",
    ]
    text_body = "\n".join(lines)

    # HTML body
    trend_rows = ""
    for i, t in enumerate(topics[:3], 1):
        cls = t.get("classification", "")
        badge_color = "#22c55e" if "SPIK" in cls else "#ef4444" if "DECLIN" in cls else "#f59e0b"
        badge_label = "↑ Spiking" if "SPIK" in cls else "↓ Declining" if "DECLIN" in cls else "→ Stable"
        trend_rows += f"""
        <tr>
          <td style="padding:16px 0;border-bottom:1px solid #2d2d30;">
            <div style="display:flex;align-items:flex-start;gap:12px;">
              <span style="font-family:JetBrains Mono,monospace;font-size:18px;
                           font-weight:700;color:rgba(255,255,255,0.2);min-width:20px;">{i}</span>
              <div style="flex:1;">
                <div style="font-size:15px;font-weight:700;color:#e5e2e3;
                            line-height:1.4;margin-bottom:6px;">{t.get('headline','')}</div>
                {"<div style='font-size:13px;color:#94a3b8;line-height:1.5;margin-bottom:6px;'>" + t['what_happened'] + "</div>" if t.get('what_happened') else ""}
                {"<div style='font-size:12px;color:#22c55e;'>💡 " + t['pm_action'] + "</div>" if t.get('pm_action') else ""}
              </div>
              <span style="flex-shrink:0;padding:4px 10px;border-radius:999px;
                           background:{badge_color}22;border:1px solid {badge_color}66;
                           color:{badge_color};font-size:11px;font-weight:700;
                           white-space:nowrap;">{badge_label}</span>
            </div>
          </td>
        </tr>"""

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#0d0d0e;font-family:Inter,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0e;">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#131314;border:1px solid #2d2d30;border-radius:16px;overflow:hidden;">
        <!-- Header -->
        <tr><td style="padding:28px 32px;border-bottom:1px solid #2d2d30;">
          <span style="font-family:Inter,sans-serif;font-size:18px;font-weight:800;color:#e5e2e3;">
            ◈ TrendLens
          </span>
          <span style="float:right;font-size:12px;color:#5a5a5e;padding-top:4px;">
            {freq_label} digest
          </span>
        </td></tr>
        <!-- Title -->
        <tr><td style="padding:24px 32px 8px;">
          <div style="font-size:13px;font-family:monospace;text-transform:uppercase;
                      letter-spacing:0.08em;color:#5a5a5e;margin-bottom:8px;">
            Trends for
          </div>
          <div style="font-size:22px;font-weight:800;color:#e5e2e3;letter-spacing:-0.5px;">
            {domain}
          </div>
        </td></tr>
        <!-- Trends -->
        <tr><td style="padding:0 32px 24px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {trend_rows}
          </table>
        </td></tr>
        <!-- CTA -->
        <tr><td style="padding:20px 32px 28px;border-top:1px solid #2d2d30;text-align:center;">
          <a href="http://localhost:8000/app"
             style="display:inline-block;padding:12px 28px;background:#22c55e;
                    color:#003915;font-weight:700;font-size:14px;border-radius:999px;
                    text-decoration:none;">View full dashboard →</a>
        </td></tr>
        <!-- Footer -->
        <tr><td style="padding:16px 32px;border-top:1px solid #2d2d30;
                       font-size:11px;color:#5a5a5e;text-align:center;">
          You're receiving this because you set up a {freq_label.lower()} digest on TrendLens.
          <a href="http://localhost:8000/settings.html"
             style="color:#5a5a5e;text-decoration:underline;margin-left:4px;">Unsubscribe</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"TrendLens {freq_label} Digest — {domain}"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(from_addr, to_email, msg.as_string())

    log.info(f"Digest sent | to={to_email!r} domain={domain!r} frequency={frequency}")
