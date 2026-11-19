import os
import math
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


URGENCY_COLOR = {
    "this week":     "#EF4444",
    "this month":    "#F59E0B",
    "next 3 months": "#0A8F6C",
}

URGENCY_LABEL = {
    "this week":     "🔴 Urgent — This Week",
    "this month":    "🟡 Due This Month",
    "next 3 months": "🟢 Scheduled — Next 3 Months",
}


def _get_smtp_config() -> dict:
    smtp_user = os.getenv("SMTP_USER")
    return {
        "host":       os.getenv("SMTP_HOST", "smtp-relay.brevo.com"),
        "port":       int(os.getenv("SMTP_PORT", "587")),
        "user":       smtp_user,
        "password":   os.getenv("SMTP_PASSWORD"),
        "from_name":  os.getenv("SMTP_FROM_NAME", "HealthGuardian AI"),
        # SMTP_FROM_EMAIL = verified sender in Brevo; falls back to SMTP_USER
        "from_email": os.getenv("SMTP_FROM_EMAIL") or smtp_user,
    }


def _send(msg: MIMEMultipart, c: dict, to_email: str) -> bool:
    if not c["user"] or not c["password"]:
        print("[Email] SMTP credentials not configured — skipping.")
        return False
    try:
        with smtplib.SMTP(c["host"], c["port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(c["user"], c["password"])
            server.sendmail(c["from_email"], to_email, msg.as_string())
        print(f"[Email] Sent '{msg['Subject']}' to {to_email}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send to {to_email}: {e}")
        return False


def _base_msg(subject: str, to_email: str, c: dict) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{c['from_name']} <{c['from_email']}>"
    msg["To"]      = to_email
    msg["Reply-To"] = msg["From"]
    return msg


# ─── HTML Builders ────────────────────────────────────────────────────────────

def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 1)


def _build_lab_comparison_html(user_name: str, test_lab_map: list, user_lat: float = None, user_lng: float = None) -> str:
    today = datetime.now().strftime("%d %B %Y")

    sections = ""
    for entry in test_lab_map:
        test_name = entry["test_name"]
        labs      = entry["labs"]  # sorted by price
        best_price = labs[0]["price_inr"] if labs else 0

        lab_rows = ""
        for i, lab in enumerate(labs):
            is_best   = i == 0
            savings   = lab["price_inr"] - best_price
            bg        = "#F0FDF4" if is_best else "#FFFFFF"
            badge     = "<span style='display:inline-block;background:#0A8F6C;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:6px;'>BEST PRICE</span>" if is_best else ""
            savings_str = f"<div style='font-size:11px;color:#EF4444;'>+Rs.{savings} more</div>" if savings > 0 else ""
            stars     = "&#9733;" * int(float(lab.get("rating") or 0)) + "&#9734;" * (5 - int(float(lab.get("rating") or 0)))
            accredited = "<span style='font-size:10px;color:#0A8F6C;font-weight:600;'>NABL Accredited</span>" if lab.get("accredited") else ""

            # Use is_nearby flag set by backend cross-match
            is_nearby      = lab.get("is_nearby", False)
            nearby_dist    = lab.get("nearby_distance")
            distance_badge = ""
            nearby_badge   = ""
            address_block  = f"<div style='font-size:11px;color:#6B7280;margin-top:2px;'>{lab.get('address','')}</div>" if lab.get('address') else ""

            if is_nearby:
                nearby_badge  = "<span style='display:inline-block;background:#FEF9C3;color:#854D0E;font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:4px;'>NEARBY</span>"
                dist_label    = f"{nearby_dist} m away" if nearby_dist else "Near you"
                distance_badge = f"<span style='display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:10px;font-weight:600;padding:2px 8px;border-radius:999px;margin-left:4px;'>{dist_label}</span>"
                # Use Mappls address (actual nearby branch) not the generic partner address
                display_address = lab.get("nearby_address") or lab.get("address", "")
                address_block = f"""
                    <div style='margin-top:6px;background:#FFFBEB;border-left:3px solid #F59E0B;border-radius:0 6px 6px 0;padding:6px 10px;'>
                      <div style='font-size:10px;font-weight:700;color:#92400E;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;'>Nearby Branch Address</div>
                      <div style='font-size:12px;color:#111827;'>{display_address}</div>
                      <div style='font-size:11px;color:#6B7280;margin-top:2px;'>Phone: {lab.get('phone','N/A')}</div>
                    </div>"""
            elif user_lat and user_lng and lab.get("lat") and lab.get("lng"):
                dist = _haversine_km(user_lat, user_lng, lab["lat"], lab["lng"])
                distance_badge = f"<span style='display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:10px;font-weight:600;padding:2px 8px;border-radius:999px;margin-left:4px;'>{dist} km away</span>"

            lab_rows += f"""
            <tr style="background:{bg}">
              <td style="padding:12px 16px;border-bottom:1px solid #F3F4F6;vertical-align:top;">
                <div style="font-weight:700;font-size:13px;color:#111827;">{lab['name']}{badge}{nearby_badge}{distance_badge}</div>
                {address_block}
                <div style="font-size:11px;color:#F59E0B;margin-top:2px;">{stars} <span style='color:#6B7280;'>({lab.get('rating','N/A')})</span></div>
                <div style="font-size:11px;color:#9CA3AF;margin-top:2px;">Timings: {lab.get('timings','N/A')}</div>
                {accredited}
              </td>
              <td style="padding:12px 16px;border-bottom:1px solid #F3F4F6;text-align:center;vertical-align:middle;min-width:100px;">
                <div style="font-size:18px;font-weight:800;color:{'#0A8F6C' if is_best else '#111827'};">Rs.{lab['price_inr']}</div>
                {savings_str}
              </td>
            </tr>"""

        sections += f"""
        <tr><td style="padding:16px 32px 0;">
          <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:8px;">🔬 {test_name}</div>
          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;margin-bottom:8px;">
            <thead><tr style="background:#F9FAFB;">
              <th style="padding:10px 16px;text-align:left;font-size:11px;color:#6B7280;font-weight:600;">LAB &amp; DETAILS</th>
              <th style="padding:10px 16px;text-align:center;font-size:11px;color:#6B7280;font-weight:600;">PRICE</th>
            </tr></thead>
            <tbody>{lab_rows}</tbody>
          </table>
        </td></tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F7FA;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F7FA;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#0F172A,#1E3A5F);padding:28px;text-align:center;">
    <div style="font-size:26px;font-weight:800;color:#FFFFFF;">Best Labs Near You</div>
    <div style="font-size:13px;color:#93C5FD;margin-top:6px;">Price Comparison for Your Recommended Tests - {today}</div>
  </td></tr>
  <tr><td style="padding:24px 32px 8px;">
    <div style="font-size:19px;font-weight:700;color:#111827;">Hi {user_name}</div>
    <div style="font-size:14px;color:#6B7280;margin-top:8px;line-height:1.6;">Based on your AI health recommendations, here's a price comparison of the best labs near you in Jaipur. We've highlighted the most affordable option for each test.</div>
  </td></tr>
  {sections}
  <tr><td style="padding:24px 32px;text-align:center;">
    <a href="#" style="display:inline-block;background:#0F172A;color:#FFFFFF;font-size:14px;font-weight:700;padding:12px 32px;border-radius:999px;text-decoration:none;">Book at Best Price</a>
  </td></tr>
  <tr><td style="background:#F8FAFC;padding:16px 32px;text-align:center;border-top:1px solid #E2E8F0;">
    <div style="font-size:11px;color:#94A3B8;">Prices sourced from lab websites. Not a medical diagnosis. | HealthGuardian AI, Jaipur</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def send_lab_comparison_email(to_email: str, user_name: str, test_lab_map: list, user_lat: float = None, user_lng: float = None) -> bool:
    c = _get_smtp_config()
    msg = _base_msg(f"Best labs near you for your health checkups, {user_name}!", to_email, c)
    plain = f"Hi {user_name},\n\nHere are the best labs near you in Jaipur for your recommended tests:\n\n"
    for entry in test_lab_map:
        plain += f"{entry['test_name']}:\n"
        for lab in entry["labs"]:
            dist_str = ""
            addr_str = ""
            if user_lat and user_lng and lab.get("lat") and lab.get("lng"):
                dist = _haversine_km(user_lat, user_lng, lab["lat"], lab["lng"])
                dist_str = f" | {dist} km away"
            if lab.get("is_nearby"):
                display_address = lab.get("nearby_address") or lab.get("address", "")
                dist_label = f"{lab.get('nearby_distance')} m away" if lab.get("nearby_distance") else "Near you"
                addr_str = f"\n      Nearby Branch: {display_address} | {dist_label} | Phone: {lab.get('phone','N/A')}"
            plain += f"  - {lab['name']}: Rs.{lab['price_inr']} | Rating: {lab.get('rating','N/A')}{dist_str}{addr_str}\n"
        plain += "\n"
    plain += "HealthGuardian AI"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_lab_comparison_html(user_name, test_lab_map, user_lat, user_lng), "html"))
    return _send(msg, c, to_email)


def _build_recommendation_html(user_name: str, proactive_message: str, recommendations: list) -> str:
    today = datetime.now().strftime("%d %B %Y")
    rows = ""
    for i, rec in enumerate(recommendations, 1):
        urgency  = rec.get("urgency", "this month")
        color    = URGENCY_COLOR.get(urgency, "#0A8F6C")
        label    = URGENCY_LABEL.get(urgency, urgency)
        triggers = ", ".join(rec.get("triggers", []))
        rows += f"""
        <tr>
          <td style="padding:16px;border-bottom:1px solid #F3F4F6;vertical-align:top;">
            <div style="font-weight:700;font-size:15px;color:#111827;margin-bottom:4px;">{i}. {rec.get('package','Health Test')}</div>
            <div style="font-size:13px;color:#6B7280;margin-bottom:6px;">{rec.get('reason','')}</div>
            <div style="font-size:12px;color:#9CA3AF;">Triggers: {triggers}</div>
          </td>
          <td style="padding:16px;border-bottom:1px solid #F3F4F6;text-align:center;vertical-align:top;min-width:140px;">
            <div style="font-size:22px;font-weight:800;color:#0A8F6C;">Rs.{rec.get('best_price_inr') or 'N/A'}</div>
            <div style="font-size:12px;color:#6B7280;margin-top:2px;">{rec.get('best_lab','')}</div>
            <div style="margin-top:8px;display:inline-block;padding:3px 10px;border-radius:999px;background:{color}18;color:{color};font-size:11px;font-weight:600;">{label}</div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F7FA;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F7FA;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#0A8F6C,#059669);padding:32px;text-align:center;">
    <div style="font-size:26px;font-weight:800;color:#FFFFFF;">HealthGuardian AI</div>
    <div style="font-size:13px;color:#A7F3D0;margin-top:6px;">Your Personalized Health Report - {today}</div>
  </td></tr>
  <tr><td style="padding:28px 32px 8px;">
    <div style="font-size:19px;font-weight:700;color:#111827;">Hi {user_name}</div>
    <div style="font-size:14px;color:#6B7280;margin-top:8px;line-height:1.6;">{proactive_message}</div>
  </td></tr>
  <tr><td style="padding:16px 32px;">
    <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:12px;">AI-Recommended Health Tests</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;">
      <thead><tr style="background:#F9FAFB;">
        <th style="padding:12px 16px;text-align:left;font-size:12px;color:#6B7280;font-weight:600;">TEST / PACKAGE</th>
        <th style="padding:12px 16px;text-align:center;font-size:12px;color:#6B7280;font-weight:600;">BEST PRICE &amp; LAB</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </td></tr>
  <tr><td style="padding:24px 32px;text-align:center;">
    <a href="#" style="display:inline-block;background:#0A8F6C;color:#FFFFFF;font-size:14px;font-weight:700;padding:12px 32px;border-radius:999px;text-decoration:none;">Book Now at Best Price</a>
  </td></tr>
  <tr><td style="background:#F9FAFB;padding:16px 32px;text-align:center;border-top:1px solid #E5E7EB;">
    <div style="font-size:11px;color:#9CA3AF;">Not a medical diagnosis. Consult your doctor before any health decisions. | HealthGuardian AI, Jaipur</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _build_reminders_html(user_name: str, reminders: list, insight: str) -> str:
    today = datetime.now().strftime("%d %B %Y")
    rows = ""
    for i, rem in enumerate(reminders, 1):
        urgency = rem.get("urgency", "this month")
        color   = URGENCY_COLOR.get(urgency, "#0A8F6C")
        label   = URGENCY_LABEL.get(urgency, urgency)
        rows += f"""
        <tr>
          <td style="padding:14px 16px;border-bottom:1px solid #F3F4F6;vertical-align:top;">
            <div style="font-weight:700;font-size:14px;color:#111827;">{i}. {rem.get('test_name','')}</div>
            <div style="font-size:12px;color:#6B7280;">{rem.get('reason','')}</div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid #F3F4F6;text-align:center;vertical-align:top;min-width:120px;">
            <div style="font-size:11px;color:#9CA3AF;">Due: {rem.get('due_date','TBD')}</div>
            <div style="margin-top:4px;display:inline-block;padding:3px 10px;border-radius:999px;background:{color}18;color:{color};font-size:11px;font-weight:600;">{label}</div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F7FA;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F7FA;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#F59E0B,#D97706);padding:28px;text-align:center;">
    <div style="font-size:26px;font-weight:800;color:#FFFFFF;">Health Reminders</div>
    <div style="font-size:13px;color:#FEF3C7;margin-top:6px;">HealthGuardian AI - {today}</div>
  </td></tr>
  <tr><td style="padding:24px 32px 8px;">
    <div style="font-size:19px;font-weight:700;color:#111827;">Hi {user_name}</div>
    <div style="font-size:14px;color:#6B7280;margin-top:8px;line-height:1.6;">{insight}</div>
  </td></tr>
  <tr><td style="padding:16px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;">
      <thead><tr style="background:#FFFBEB;">
        <th style="padding:10px 16px;text-align:left;font-size:11px;color:#92400E;font-weight:600;">REMINDER</th>
        <th style="padding:10px 16px;text-align:center;font-size:11px;color:#92400E;font-weight:600;">DUE &amp; URGENCY</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </td></tr>
  <tr><td style="padding:20px 32px;text-align:center;">
    <a href="#" style="display:inline-block;background:#F59E0B;color:#FFFFFF;font-size:14px;font-weight:700;padding:12px 32px;border-radius:999px;text-decoration:none;">Book Now</a>
  </td></tr>
  <tr><td style="background:#FFFBEB;padding:16px 32px;text-align:center;border-top:1px solid #FDE68A;">
    <div style="font-size:11px;color:#92400E;">Not a medical diagnosis. Consult your doctor. | HealthGuardian AI, Jaipur</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _build_agent_activity_html(user_name: str, agent_result: dict, actions: dict, run_at: str) -> str:
    reminders   = agent_result.get("reminders_to_create", [])
    notifs      = agent_result.get("notifications_to_send", [])
    reasoning   = agent_result.get("agent_reasoning", "")
    insight     = agent_result.get("proactive_insight", "")
    rem_count   = actions.get("reminders_created", 0)
    notif_count = actions.get("notifications_sent", 0)

    rem_items = "".join(
        f"<li style='margin-bottom:6px;font-size:13px;color:#374151;'><strong>{r.get('test_name')}</strong> - {r.get('urgency','')} ({r.get('trigger','')})</li>"
        for r in reminders
    )
    notif_items = "".join(
        f"<li style='margin-bottom:6px;font-size:13px;color:#374151;'><strong>[{n.get('channel','').upper()}]</strong> {n.get('title','')} - {n.get('type','')}</li>"
        for n in notifs
    )
    rem_section  = f"<tr><td style='padding:0 32px 16px;'><div style='font-size:14px;font-weight:700;color:#111827;margin-bottom:8px;'>Reminders Created</div><ul style='margin:0;padding-left:20px;'>{rem_items}</ul></td></tr>" if reminders else ""
    notif_section = f"<tr><td style='padding:0 32px 24px;'><div style='font-size:14px;font-weight:700;color:#111827;margin-bottom:8px;'>Notifications Dispatched</div><ul style='margin:0;padding-left:20px;'>{notif_items}</ul></td></tr>" if notifs else ""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F7FA;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F7FA;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#6366F1,#4F46E5);padding:28px;text-align:center;">
    <div style="font-size:26px;font-weight:800;color:#FFFFFF;">Agent Activity Report</div>
    <div style="font-size:13px;color:#C7D2FE;margin-top:6px;">HealthGuardian AI - {run_at}</div>
  </td></tr>
  <tr><td style="padding:24px 32px 8px;">
    <div style="font-size:19px;font-weight:700;color:#111827;">Hi {user_name}</div>
    <div style="font-size:14px;color:#6B7280;margin-top:6px;line-height:1.6;">{insight}</div>
  </td></tr>
  <tr><td style="padding:16px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="width:50%;padding-right:8px;">
        <div style="background:#EEF2FF;border-radius:12px;padding:16px;text-align:center;">
          <div style="font-size:28px;font-weight:800;color:#6366F1;">{rem_count}</div>
          <div style="font-size:12px;color:#6B7280;margin-top:4px;">Reminders Created</div>
        </div>
      </td>
      <td style="width:50%;padding-left:8px;">
        <div style="background:#F0FDF4;border-radius:12px;padding:16px;text-align:center;">
          <div style="font-size:28px;font-weight:800;color:#0A8F6C;">{notif_count}</div>
          <div style="font-size:12px;color:#6B7280;margin-top:4px;">Notifications Sent</div>
        </div>
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:8px 32px 16px;">
    <div style="background:#F9FAFB;border-left:4px solid #6366F1;border-radius:0 8px 8px 0;padding:14px 16px;">
      <div style="font-size:12px;font-weight:700;color:#6366F1;text-transform:uppercase;margin-bottom:6px;">Agent Reasoning</div>
      <div style="font-size:13px;color:#374151;line-height:1.6;">{reasoning}</div>
    </div>
  </td></tr>
  {rem_section}
  {notif_section}
  <tr><td style="background:#EEF2FF;padding:16px 32px;text-align:center;border-top:1px solid #E0E7FF;">
    <div style="font-size:11px;color:#6366F1;">Automated activity report from HealthGuardian AI, Jaipur</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _build_due_date_alert_html(user_name: str, reminders: list) -> str:
    today = datetime.now().strftime("%d %B %Y")
    rows = ""
    for rem in reminders:
        urgency   = rem.get("urgency", "this month")
        color     = URGENCY_COLOR.get(urgency, "#EF4444")
        label     = URGENCY_LABEL.get(urgency, urgency)
        days_left = rem.get("days_left", "")
        rows += f"""
        <tr>
          <td style="padding:14px 16px;border-bottom:1px solid #F3F4F6;vertical-align:top;">
            <div style="font-weight:700;font-size:14px;color:#111827;">{rem.get('test_name','')}</div>
            <div style="font-size:12px;color:#6B7280;">{rem.get('reason','')}</div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid #F3F4F6;text-align:center;vertical-align:top;min-width:120px;">
            <div style="font-size:13px;font-weight:700;color:#111827;">{rem.get('due_date','TBD')}</div>
            <div style="font-size:11px;color:#EF4444;font-weight:600;margin-top:2px;">{days_left} day(s) left</div>
            <div style="margin-top:4px;display:inline-block;padding:3px 10px;border-radius:999px;background:{color}18;color:{color};font-size:11px;font-weight:600;">{label}</div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F7FA;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F7FA;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#EF4444,#DC2626);padding:28px;text-align:center;">
    <div style="font-size:26px;font-weight:800;color:#FFFFFF;">Upcoming Health Due Dates</div>
    <div style="font-size:13px;color:#FECACA;margin-top:6px;">HealthGuardian AI - {today}</div>
  </td></tr>
  <tr><td style="padding:24px 32px 8px;">
    <div style="font-size:19px;font-weight:700;color:#111827;">Hi {user_name}</div>
    <div style="font-size:14px;color:#6B7280;margin-top:8px;line-height:1.6;">Your HealthGuardian AI agent has detected that the following health checkups are coming up soon. Don't miss them - early detection saves lives and money!</div>
  </td></tr>
  <tr><td style="padding:16px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #FEE2E2;border-radius:12px;overflow:hidden;">
      <thead><tr style="background:#FEF2F2;">
        <th style="padding:10px 16px;text-align:left;font-size:11px;color:#991B1B;font-weight:600;">CHECKUP</th>
        <th style="padding:10px 16px;text-align:center;font-size:11px;color:#991B1B;font-weight:600;">DUE DATE</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </td></tr>
  <tr><td style="padding:20px 32px;text-align:center;">
    <a href="#" style="display:inline-block;background:#EF4444;color:#FFFFFF;font-size:14px;font-weight:700;padding:12px 32px;border-radius:999px;text-decoration:none;">Book Now</a>
  </td></tr>
  <tr><td style="background:#FEF2F2;padding:16px 32px;text-align:center;border-top:1px solid #FEE2E2;">
    <div style="font-size:11px;color:#991B1B;">Automated due-date alert. Not a medical diagnosis. | HealthGuardian AI, Jaipur</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


# ─── Public Senders ───────────────────────────────────────────────────────────

def send_recommendation_email(to_email, user_name, proactive_message, recommendations) -> bool:
    c = _get_smtp_config()
    msg = _base_msg(f"Your AI Health Report is Ready, {user_name}!", to_email, c)
    plain = f"Hi {user_name},\n\n{proactive_message}\n\n" + "\n".join(
        f"- {r.get('package')} | Rs.{r.get('best_price_inr') or 'N/A'} at {r.get('best_lab')} | {r.get('urgency')}"
        for r in recommendations
    ) + "\n\nHealthGuardian AI"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_recommendation_html(user_name, proactive_message, recommendations), "html"))
    return _send(msg, c, to_email)


def send_reminders_email(to_email, user_name, reminders, insight) -> bool:
    c = _get_smtp_config()
    msg = _base_msg(f"You have {len(reminders)} health reminder(s), {user_name}!", to_email, c)
    plain = f"Hi {user_name},\n\n{insight}\n\n" + "\n".join(
        f"- {r.get('test_name')} | Due: {r.get('due_date','TBD')} | {r.get('urgency','')}"
        for r in reminders
    ) + "\n\nHealthGuardian AI"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_reminders_html(user_name, reminders, insight), "html"))
    return _send(msg, c, to_email)


def send_agent_activity_email(to_email, user_name, agent_result, actions, run_at) -> bool:
    c = _get_smtp_config()
    msg = _base_msg(f"HealthGuardian Agent ran for you, {user_name}!", to_email, c)
    plain = (
        f"Hi {user_name},\n\n"
        f"{agent_result.get('proactive_insight','')}\n\n"
        f"Reminders created: {actions.get('reminders_created',0)}\n"
        f"Notifications sent: {actions.get('notifications_sent',0)}\n\n"
        f"Agent reasoning: {agent_result.get('agent_reasoning','')}\n\n"
        f"HealthGuardian AI"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_agent_activity_html(user_name, agent_result, actions, run_at), "html"))
    return _send(msg, c, to_email)


def send_due_date_alert_email(to_email, user_name, reminders) -> bool:
    c = _get_smtp_config()
    msg = _base_msg(f"{len(reminders)} health checkup(s) due soon, {user_name}!", to_email, c)
    plain = f"Hi {user_name},\n\nThe following health checkups are due soon:\n\n" + "\n".join(
        f"- {r.get('test_name')} | Due: {r.get('due_date')} | {r.get('days_left')} day(s) left"
        for r in reminders
    ) + "\n\nBook now at the best price.\n\nHealthGuardian AI"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_due_date_alert_html(user_name, reminders), "html"))
    return _send(msg, c, to_email)
