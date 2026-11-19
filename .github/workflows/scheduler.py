"""
Reminder Due-Date Scheduler
Runs a background job every day at 8 AM to check all pending reminders.
Sends email alerts at 3 checkpoints before the due date: 7 days, 3 days, 1 day.
Tracks notified_at per reminder to avoid duplicate emails.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, date, timedelta
from database import get_db_connection
from email_service import send_due_date_alert_email, send_lab_comparison_email

# Days before due date to send alert emails
ALERT_DAYS = [7, 3, 1]


def check_and_send_due_date_alerts():
    print(f"[Scheduler] Running due-date alert check at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all pending reminders with due dates, joined with user email
    cursor.execute("""
        SELECT r.id, r.user_id, r.test_name, r.reason, r.urgency, r.due_date, r.notified_at,
               u.name, u.email, u.user_lat, u.user_lng
        FROM reminders r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.status = 'pending'
          AND r.due_date IS NOT NULL
          AND r.due_date != ''
          AND u.email IS NOT NULL
          AND u.email != ''
    """)
    reminders = [dict(r) for r in cursor.fetchall()]

    today = date.today()

    # Group reminders by user that need alerting today
    user_alerts: dict[str, dict] = {}

    for rem in reminders:
        try:
            due = datetime.strptime(rem["due_date"], "%Y-%m-%d").date()
        except ValueError:
            continue

        days_left = (due - today).days

        # Only alert at the defined checkpoints
        if days_left not in ALERT_DAYS:
            continue

        # Check if we already sent an alert for this exact days_left checkpoint
        notified_at = rem.get("notified_at") or ""
        checkpoint_key = f"{days_left}d"
        if checkpoint_key in notified_at:
            continue

        user_id = rem["user_id"]
        if user_id not in user_alerts:
            user_alerts[user_id] = {
                "email":    rem["email"],
                "name":     rem["name"],
                "user_lat": rem.get("user_lat"),
                "user_lng": rem.get("user_lng"),
                "reminders": [],
            }

        user_alerts[user_id]["reminders"].append({
            "id":        rem["id"],
            "test_name": rem["test_name"],
            "reason":    rem["reason"],
            "urgency":   rem["urgency"],
            "due_date":  rem["due_date"],
            "days_left": days_left,
        })

    # Send one consolidated email per user and mark reminders as notified
    now = datetime.now().isoformat()
    for user_id, data in user_alerts.items():
        sent = send_due_date_alert_email(
            to_email=data["email"],
            user_name=data["name"],
            reminders=data["reminders"],
        )
        if sent:
            for rem in data["reminders"]:
                checkpoint_key = f"{rem['days_left']}d"
                cursor.execute(
                    "UPDATE reminders SET notified_at = ? WHERE id = ?",
                    (f"{now} [{checkpoint_key}]", rem["id"]),
                )
            print(f"[Scheduler] Sent due-date alert to {data['email']} for {len(data['reminders'])} reminder(s)")

            # Build lab comparison with nearby cross-match
            test_lab_map = []
            # Fetch this user's nearby labs
            cursor.execute(
                "SELECT name, address, distance FROM nearby_labs WHERE user_id = ?",
                (user_id,),
            )
            nearby_names = {r["name"].lower(): dict(r) for r in cursor.fetchall()}

            for rem in data["reminders"]:
                cursor.execute(
                    """
                    SELECT lp.lab_name as name, lp.price_inr,
                           l.address, l.phone, l.rating, l.timings, l.accredited, l.lat, l.lng
                    FROM lab_prices lp
                    LEFT JOIN labs l ON l.name = lp.lab_name
                    WHERE lp.test_name LIKE ?
                    ORDER BY lp.price_inr ASC
                    """,
                    (f"%{rem['test_name']}%",),
                )
                labs = [dict(r) for r in cursor.fetchall()]
                for lab in labs:
                    lab_lower = lab["name"].lower()
                    matched = next(
                        (nb for nb_name, nb in nearby_names.items() if lab_lower in nb_name or nb_name in lab_lower),
                        None,
                    )
                    lab["is_nearby"]       = matched is not None
                    lab["nearby_distance"] = matched["distance"] if matched else None
                    lab["nearby_address"]  = matched["address"] if matched else None
                if labs:
                    test_lab_map.append({"test_name": rem["test_name"], "labs": labs})

            if test_lab_map:
                send_lab_comparison_email(
                    to_email=data["email"],
                    user_name=data["name"],
                    test_lab_map=test_lab_map,
                    user_lat=data.get("user_lat"),
                    user_lng=data.get("user_lng"),
                )
                print(f"[Scheduler] Sent lab comparison email to {data['email']}")

    conn.commit()
    conn.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_send_due_date_alerts,
        trigger=CronTrigger(hour=8, minute=0),   # Every day at 8:00 AM
        id="due_date_alerts",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Due-date alert scheduler started — runs daily at 8:00 AM")
    return scheduler
