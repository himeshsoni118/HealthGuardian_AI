from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()
import os
import requests

from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from database import get_db_connection, init_db, seed_labs
from scraper import LabPriceScraper
from pdf_processor import extract_medical_history
from agent_recommender import generate_recommendations
from agent_monitor import run_agent_for_user, execute_agent_actions
from email_service import send_recommendation_email, send_lab_comparison_email
from scheduler import start_scheduler
import json

app = FastAPI(title="HealthGuardian AI — Agentic Health Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    seed_labs()
    start_scheduler()


# ─── Scraping ─────────────────────────────────────────────────────────────────

@app.post("/scrape-prices")
async def trigger_scrape(background_tasks: BackgroundTasks):
    def run_scrape():
        try:
            scraper = LabPriceScraper(city="Jaipur")
            scraper.scrape_all()
        except Exception as e:
            print(f"[Scrape Background] Error: {e}")

    background_tasks.add_task(run_scrape)
    return {
        "status": "success",
        "message": "Scraping started in background",
        "next_steps": "Wait 30-90 seconds then check /prices",
    }


# ─── Lab Prices ───────────────────────────────────────────────────────────────

@app.get("/prices")
async def get_prices(test_name: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if test_name:
        cursor.execute(
            "SELECT * FROM lab_prices WHERE test_name LIKE ? ORDER BY price_inr",
            (f"%{test_name}%",),
        )
    else:
        cursor.execute("SELECT * FROM lab_prices ORDER BY price_inr")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ─── Nearby Labs ─────────────────────────────────────────────────────────────

class NearbyLab(BaseModel):
    name: str
    address: Optional[str] = None
    distance: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    rating: Optional[str] = None
    open_now: Optional[bool] = True
@app.get("/nearby-labs")
async def get_nearby_labs(
    lat: float,
    lng: float,
    radius: int = 5000
):
    """
    Return nearby diagnostic labs.

    For now this uses the labs already available in the local database.
    This keeps the app working without depending on Mappls.
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            name,
            address,
            lat,
            lng,
            rating
        FROM labs
    """)

    rows = cursor.fetchall()
    conn.close()

    labs = []

    for i, row in enumerate(rows):
        labs.append({
            "id": f"lab_{i}",
            "name": row["name"],
            "address": row["address"] or "",
            "distance": 0,
            "lat": row["lat"],
            "lng": row["lng"],
            "type": "Diagnostic Center",
            "rating": str(row["rating"] or "4.0"),
            "reviewCount": 0,
            "openNow": True,
        })

    return {"labs": labs[:12]}

@app.post("/users/{user_id}/nearby-labs")
async def save_nearby_labs(user_id: str, labs: list[NearbyLab]):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Clear old nearby labs for this user and replace with fresh results
    cursor.execute("DELETE FROM nearby_labs WHERE user_id = ?", (user_id,))
    now = datetime.now().isoformat()
    for lab in labs:
        cursor.execute(
            """INSERT INTO nearby_labs (user_id, name, address, distance, lat, lng, rating, open_now, saved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, lab.name, lab.address, lab.distance, lab.lat, lab.lng,
             lab.rating, 1 if lab.open_now else 0, now),
        )
    conn.commit()
    conn.close()
    return {"status": "saved", "count": len(labs)}


# ─── User Profile ─────────────────────────────────────────────────────────────

@app.post("/users/{user_id}/profile")
async def save_profile(
    user_id: str,
    name: str = Form(),
    dob: str = Form(),
    marital_status: str = Form(),
    mobile: str = Form(),
    email: str = Form(default=None),
    user_lat: float = Form(default=None),
    user_lng: float = Form(default=None),
    medical_history_files: list[UploadFile] = File(default=[]),
):
    history_parts = []
    for f in medical_history_files:
        file_bytes = await f.read()
        mime_type = f.content_type or "application/pdf"
        try:
            text = extract_medical_history(file_bytes, mime_type)
            if text.strip():
                history_parts.append(f"[{f.filename}]\n{text}")
        except Exception as e:
            print(f"[Profile] Failed to extract {f.filename}: {e}")
    history_text = "\n\n".join(history_parts)[:8000]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO users (user_id, name, dob, marital_status, mobile, email, user_lat, user_lng, medical_history, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (user_id, name, dob, marital_status, mobile, email, user_lat, user_lng, history_text, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"status": "profile saved", "user_id": user_id}


@app.get("/users/{user_id}")
async def get_user(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row)


# ─── AI Recommendations ──────────────────────────────────────────────────────

@app.get("/recommend/{user_id}")
async def get_recommendations(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        raise HTTPException(404, "User not found")
    user = dict(user_row)

    if user.get("dob"):
        try:
            dob = datetime.strptime(user["dob"], "%Y-%m-%d")
            user["age"] = datetime.now().year - dob.year
        except Exception:
            user["age"] = "unknown"

    cursor.execute(
        "SELECT * FROM lab_prices WHERE city='Jaipur' ORDER BY price_inr LIMIT 100"
    )
    prices = [dict(row) for row in cursor.fetchall()]
    conn.close()

    recs = generate_recommendations(user, prices)
    return recs


# ─── Agentic Health Monitor ──────────────────────────────────────────────────

@app.post("/agent/monitor/{user_id}")
async def trigger_agent_monitor(user_id: str):
    """
    Trigger the autonomous agentic AI to monitor a user's health timeline.
    The agent independently decides what reminders and notifications to create.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        raise HTTPException(404, "User not found")
    user = dict(user_row)

    if user.get("dob"):
        try:
            dob = datetime.strptime(user["dob"], "%Y-%m-%d")
            user["age"] = datetime.now().year - dob.year
        except Exception:
            pass

    cursor.execute(
        "SELECT * FROM lab_prices WHERE city='Jaipur' ORDER BY price_inr LIMIT 100"
    )
    prices = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Agent autonomously analyzes and decides
    agent_result = run_agent_for_user(user, prices)

    # Execute the agent's decisions
    actions = execute_agent_actions(user_id, agent_result, user)

    # Send recommendation email if user has an email on file
    if user.get("email"):
        recs = agent_result.get("reminders_to_create", [])
        # Shape reminders into recommendation format for the email
        email_recs = [
            {
                "package":       r.get("test_name", ""),
                "reason":        r.get("reason", ""),
                "triggers":      [r.get("trigger", "")],
                "urgency":       r.get("urgency", "this month"),
                "best_price_inr": next(
                    (p["price_inr"] for p in prices if r["test_name"].upper() in p["test_name"].upper()),
                    None,
                ),
                "best_lab": next(
                    (p["lab_name"] for p in prices if r["test_name"].upper() in p["test_name"].upper()),
                    "Best lab in Jaipur",
                ),
            }
            for r in recs
        ]
        send_recommendation_email(
            to_email=user["email"],
            user_name=user["name"],
            proactive_message=agent_result.get("proactive_insight", ""),
            recommendations=email_recs,
        )

        # Build per-test lab comparison from DB (all labs, sorted by price)
        # Only send if agent actually created new reminders this run
        if recs:
            conn2 = get_db_connection()
            cursor2 = conn2.cursor()

            # Fetch user's saved nearby labs to cross-match with partner labs
            cursor2.execute(
                "SELECT name, address, distance, lat, lng, rating FROM nearby_labs WHERE user_id = ?",
                (user_id,),
            )
            nearby = [dict(r) for r in cursor2.fetchall()]
            # Build a set of nearby lab name fragments for fuzzy matching
            nearby_names = {n["name"].lower(): n for n in nearby}

            test_lab_map = []
            for r in recs:
                test_name = r.get("test_name", "")
                cursor2.execute(
                    """
                    SELECT lp.lab_name as name, lp.price_inr, lp.has_offer, lp.offer_text,
                           l.address, l.phone, l.rating, l.timings, l.accredited, l.lat, l.lng
                    FROM lab_prices lp
                    LEFT JOIN labs l ON l.name = lp.lab_name
                    WHERE lp.test_name LIKE ?
                    ORDER BY lp.price_inr ASC
                    """,
                    (f"%{test_name}%",),
                )
                labs = [dict(row) for row in cursor2.fetchall()]

                # Cross-match: mark partner labs that appear in user's nearby list
                for lab in labs:
                    lab_lower = lab["name"].lower()
                    matched = next(
                        (nb for nb_name, nb in nearby_names.items() if lab_lower in nb_name or nb_name in lab_lower),
                        None,
                    )
                    lab["is_nearby"]       = matched is not None
                    lab["nearby_distance"] = matched["distance"] if matched else None
                    # Use Mappls address for nearby labs — it's the actual branch location
                    lab["nearby_address"]  = matched["address"] if matched else None

                if labs:
                    test_lab_map.append({"test_name": test_name, "labs": labs})
            conn2.close()

            if test_lab_map:
                send_lab_comparison_email(
                    to_email=user["email"],
                    user_name=user["name"],
                    test_lab_map=test_lab_map,
                    user_lat=user.get("user_lat"),
                    user_lng=user.get("user_lng"),
                )

    return {
        "status": "agent_completed",
        "agent_reasoning": agent_result.get("agent_reasoning", ""),
        "proactive_insight": agent_result.get("proactive_insight", ""),
        "actions_taken": actions,
        "reminders": agent_result.get("reminders_to_create", []),
        "notifications": agent_result.get("notifications_to_send", []),
    }


@app.post("/agent/monitor-all")
async def trigger_agent_monitor_all():
    """
    Autonomous batch scan: agent monitors ALL users' health timelines.
    This simulates a scheduled cron job in production.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row["user_id"] for row in cursor.fetchall()]
    conn.close()

    results = []
    for uid in users:
        try:
            result = await trigger_agent_monitor(uid)
            results.append({"user_id": uid, "status": "ok", "actions": result["actions_taken"]})
        except Exception as e:
            results.append({"user_id": uid, "status": "error", "error": str(e)})

    return {
        "status": "batch_complete",
        "users_scanned": len(users),
        "results": results,
    }


# ─── Reminders ────────────────────────────────────────────────────────────────

@app.get("/reminders/{user_id}")
async def get_reminders(user_id: str, status: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND status = ? ORDER BY due_date",
            (user_id, status),
        )
    else:
        cursor.execute(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY due_date",
            (user_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.patch("/reminders/{reminder_id}/dismiss")
async def dismiss_reminder(reminder_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE reminders SET status = 'dismissed' WHERE id = ?", (reminder_id,)
    )
    conn.commit()
    conn.close()
    return {"status": "dismissed", "reminder_id": reminder_id}


@app.patch("/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,)
    )
    conn.commit()
    conn.close()
    return {"status": "completed", "reminder_id": reminder_id}


# ─── Appointment Booking (Simulation) ────────────────────────────────────────

@app.get("/slots/{lab_name}")
async def get_available_slots(lab_name: str, date: str = None):
    """
    Returns simulated available time slots for a lab on a given date.
    In production, this would integrate with the lab's booking system.
    """
    if not date:
        date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Simulated slot generation — different labs have different slot patterns
    base_slots = [
        "07:00 AM", "07:30 AM", "08:00 AM", "08:30 AM",
        "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM",
        "11:00 AM", "11:30 AM", "12:00 PM",
        "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM",
        "04:00 PM", "04:30 PM", "05:00 PM",
    ]

    # Simulate some slots being booked (based on date hash for consistency)
    date_hash = sum(ord(c) for c in date)
    available = []
    for i, slot in enumerate(base_slots):
        # Simple deterministic "booking" simulation
        is_booked = (date_hash + i) % 4 == 0
        available.append({
            "time": slot,
            "available": not is_booked,
        })

    return {
        "lab_name": lab_name,
        "date": date,
        "slots": available,
    }


class BookingRequest(BaseModel):
    user_id: str
    lab_name: str
    test_name: str
    date: str
    time_slot: str
    price_inr: Optional[int] = None


@app.post("/appointments/book")
async def book_appointment(booking: BookingRequest):
    """
    Book an appointment at a diagnostic lab (simulation).
    In production, this would call the lab's booking API.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check for duplicate booking
    cursor.execute(
        """SELECT id FROM appointments
           WHERE user_id = ? AND lab_name = ? AND test_name = ? AND date = ? AND status = 'confirmed'""",
        (booking.user_id, booking.lab_name, booking.test_name, booking.date),
    )
    if cursor.fetchone():
        conn.close()
        raise HTTPException(409, "You already have this test booked for this date")

    now = datetime.now().isoformat()
    cursor.execute(
        """INSERT INTO appointments (user_id, lab_name, test_name, date, time_slot, price_inr, status, booked_at)
           VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?)""",
        (booking.user_id, booking.lab_name, booking.test_name, booking.date, booking.time_slot, booking.price_inr, now),
    )

    appointment_id = cursor.lastrowid

    # Auto-create a confirmation notification
    cursor.execute(
        """INSERT INTO notifications (user_id, channel, title, message, type, sent_at)
           VALUES (?, 'push', ?, ?, 'booking', ?)""",
        (
            booking.user_id,
            "Appointment Confirmed",
            f"Your {booking.test_name} at {booking.lab_name} is booked for {booking.date} at {booking.time_slot}. Price: Rs.{booking.price_inr or 'TBD'}",
            now,
        ),
    )

    # Mark any related reminder as completed
    cursor.execute(
        """UPDATE reminders SET status = 'completed'
           WHERE user_id = ? AND test_name LIKE ? AND status = 'pending'""",
        (booking.user_id, f"%{booking.test_name}%"),
    )

    conn.commit()
    conn.close()

    return {
        "status": "confirmed",
        "appointment_id": appointment_id,
        "details": {
            "lab": booking.lab_name,
            "test": booking.test_name,
            "date": booking.date,
            "time_slot": booking.time_slot,
            "price_inr": booking.price_inr,
        },
        "message": f"Appointment confirmed at {booking.lab_name} on {booking.date} at {booking.time_slot}",
    }


@app.get("/appointments/{user_id}")
async def get_appointments(user_id: str, status: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM appointments WHERE user_id = ? AND status = ? ORDER BY date, time_slot",
            (user_id, status),
        )
    else:
        cursor.execute(
            "SELECT * FROM appointments WHERE user_id = ? ORDER BY date DESC, time_slot",
            (user_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.patch("/appointments/{appointment_id}/cancel")
async def cancel_appointment(appointment_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
        (appointment_id,),
    )
    conn.commit()
    conn.close()
    return {"status": "cancelled", "appointment_id": appointment_id}


# ─── Multi-Channel Notifications (Simulated) ─────────────────────────────────

@app.post("/notify/{user_id}")
async def send_notification(
    user_id: str,
    channel: str = "push",
    title: str = "Health Checkup Reminder",
    message: str = None,
):
    """
    Simulated multi-channel notification system.
    Channels: push, sms, email, whatsapp
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name, mobile FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "User not found")
    user = dict(user)

    if not message:
        message = f"Hi {user['name']}! Your health checkup is due. Book now to stay ahead of potential health issues."

    now = datetime.now().isoformat()
    cursor.execute(
        """INSERT INTO notifications (user_id, channel, title, message, type, sent_at)
           VALUES (?, ?, ?, ?, 'reminder', ?)""",
        (user_id, channel, title, message, now),
    )
    conn.commit()
    conn.close()

    # Simulated channel-specific responses
    channel_info = {
        "push": f"Push notification sent to device",
        "sms": f"SMS sent to {user.get('mobile', 'N/A')}",
        "email": f"Email sent to {user.get('name', 'User')}'s registered email",
        "whatsapp": f"WhatsApp message sent to {user.get('mobile', 'N/A')}",
    }

    return {
        "status": "sent",
        "channel": channel,
        "delivery": channel_info.get(channel, "Notification sent"),
        "title": title,
        "message": message,
        "simulated": True,
    }


@app.get("/notifications/{user_id}")
async def get_notifications(user_id: str, unread_only: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()
    if unread_only:
        cursor.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND read_at IS NULL ORDER BY sent_at DESC",
            (user_id,),
        )
    else:
        cursor.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY sent_at DESC LIMIT 50",
            (user_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.patch("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET read_at = ? WHERE id = ?",
        (datetime.now().isoformat(), notification_id),
    )
    conn.commit()
    conn.close()
    return {"status": "read", "notification_id": notification_id}


# ─── Agent Activity Log ──────────────────────────────────────────────────────

@app.get("/agent/history/{user_id}")
async def get_agent_history(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM agent_runs WHERE user_id = ? ORDER BY run_at DESC LIMIT 20",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ─── Health Dashboard Summary ─────────────────────────────────────────────────

@app.get("/dashboard/{user_id}")
async def get_dashboard_summary(user_id: str):
    """
    Aggregated dashboard data — single call for the mobile app.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # User
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        raise HTTPException(404, "User not found")

    # Pending reminders
    cursor.execute(
        "SELECT * FROM reminders WHERE user_id = ? AND status = 'pending' ORDER BY due_date LIMIT 10",
        (user_id,),
    )
    reminders = [dict(r) for r in cursor.fetchall()]

    # Upcoming appointments
    cursor.execute(
        "SELECT * FROM appointments WHERE user_id = ? AND status = 'confirmed' ORDER BY date LIMIT 5",
        (user_id,),
    )
    appointments = [dict(r) for r in cursor.fetchall()]

    # Unread notifications count
    cursor.execute(
        "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
    )
    unread_count = cursor.fetchone()["count"]

    # Recent agent activity
    cursor.execute(
        "SELECT * FROM agent_runs WHERE user_id = ? ORDER BY run_at DESC LIMIT 3",
        (user_id,),
    )
    agent_activity = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "reminders": reminders,
        "appointments": appointments,
        "unread_notifications": unread_count,
        "agent_activity": agent_activity,
    }


# ─── Labs (dynamically managed via DB) ────────────────────────────────────────


@app.get("/labs")
async def get_labs(city: str = None):
    """Return all active labs with addresses, ratings, and pricing stats."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if city:
        cursor.execute("SELECT * FROM labs WHERE active = 1 AND city = ?", (city,))
    else:
        cursor.execute("SELECT * FROM labs WHERE active = 1")
    lab_rows = cursor.fetchall()

    labs_response = []
    for row in lab_rows:
        lab = dict(row)
        cursor.execute(
            "SELECT COUNT(*) as test_count, MIN(price_inr) as min_price, AVG(price_inr) as avg_price FROM lab_prices WHERE lab_name = ?",
            (lab["name"],),
        )
        stats = dict(cursor.fetchone())
        lab["tests_available"] = stats["test_count"] or 0
        lab["starting_price"] = stats["min_price"]
        lab["avg_price"] = round(stats["avg_price"]) if stats["avg_price"] else None
        labs_response.append(lab)

    conn.close()
    return labs_response


@app.get("/labs/{lab_name}")
async def get_lab_detail(lab_name: str):
    """Return a single lab's full details."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM labs WHERE name = ?", (lab_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Lab not found")
    lab = dict(row)

    cursor.execute(
        "SELECT COUNT(*) as test_count, MIN(price_inr) as min_price, AVG(price_inr) as avg_price FROM lab_prices WHERE lab_name = ?",
        (lab_name,),
    )
    stats = dict(cursor.fetchone())
    lab["tests_available"] = stats["test_count"] or 0
    lab["starting_price"] = stats["min_price"]
    lab["avg_price"] = round(stats["avg_price"]) if stats["avg_price"] else None
    conn.close()
    return lab


@app.get("/labs/{lab_name}/tests")
async def get_lab_tests(lab_name: str):
    """Return all tests available at a specific lab with prices."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM labs WHERE name = ?", (lab_name,))
    lab_row = cursor.fetchone()
    details = dict(lab_row) if lab_row else {}

    cursor.execute(
        "SELECT * FROM lab_prices WHERE lab_name = ? ORDER BY price_inr",
        (lab_name,),
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "lab_name": lab_name,
        "details": details,
        "tests": [dict(row) for row in rows],
    }


class LabCreate(BaseModel):
    name: str
    address: Optional[str] = None
    city: str = "Jaipur"
    phone: Optional[str] = None
    rating: float = 0
    review_count: int = 0
    lat: Optional[float] = None
    lng: Optional[float] = None
    timings: Optional[str] = None
    accredited: bool = False


@app.post("/labs")
async def create_lab(lab: LabCreate):
    """Add a new lab to the directory."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    try:
        cursor.execute(
            """INSERT INTO labs (name, address, city, phone, rating, review_count,
               lat, lng, timings, accredited, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (lab.name, lab.address, lab.city, lab.phone, lab.rating,
             lab.review_count, lab.lat, lab.lng, lab.timings, lab.accredited,
             now, now),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(409, f"Lab already exists or invalid data: {e}")
    conn.close()
    return {"status": "created", "name": lab.name}


@app.put("/labs/{lab_name}")
async def update_lab(lab_name: str, lab: LabCreate):
    """Update an existing lab's details."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        """UPDATE labs SET address=?, city=?, phone=?, rating=?, review_count=?,
           lat=?, lng=?, timings=?, accredited=?, updated_at=?
           WHERE name=?""",
        (lab.address, lab.city, lab.phone, lab.rating, lab.review_count,
         lab.lat, lab.lng, lab.timings, lab.accredited, now, lab_name),
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Lab not found")
    conn.commit()
    conn.close()
    return {"status": "updated", "name": lab_name}


@app.delete("/labs/{lab_name}")
async def deactivate_lab(lab_name: str):
    """Soft-delete a lab (marks as inactive)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE labs SET active = 0 WHERE name = ?", (lab_name,))
    conn.commit()
    conn.close()
    return {"status": "deactivated", "name": lab_name}


# ─── Push Token Registration ─────────────────────────────────────────────────

@app.post("/users/{user_id}/push-token")
async def register_push_token(user_id: str, token: str = Form()):
    """Store the Expo push notification token for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN push_token TEXT")
    except Exception:
        pass
    cursor.execute(
        "UPDATE users SET push_token = ? WHERE user_id = ?",
        (token, user_id),
    )
    conn.commit()
    conn.close()
    return {"status": "token_registered", "user_id": user_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
