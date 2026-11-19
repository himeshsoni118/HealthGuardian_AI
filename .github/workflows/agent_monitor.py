"""
Agentic Health Monitor — Autonomous health timeline monitoring engine.

This module acts as the "brain" of HealthGuardian AI. It:
1. Continuously monitors user health timelines
2. Makes independent decisions on when checkups are due
3. Triggers reminders and notifications proactively
4. Adapts based on context (medical history, age, festivals, lifestyle triggers)
"""

import os
import json
from datetime import datetime, timedelta
from openai import AzureOpenAI
from database import get_db_connection, init_db
from email_service import send_reminders_email, send_agent_activity_email


def get_azure_client():
    return AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-12-01-preview",
    )


def run_agent_for_user(user: dict, lab_prices: list) -> dict:
    """
    Autonomous agent that analyzes a user's health profile and decides
    what reminders to create and notifications to send.
    Returns structured actions the agent decided to take.
    """
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d (%A)")

    # Calculate age
    age = "unknown"
    if user.get("dob"):
        try:
            dob = datetime.strptime(user["dob"], "%Y-%m-%d")
            age = today.year - dob.year
        except Exception:
            pass

    history = (user.get("medical_history") or "")[:4000]

    # Get existing reminders for this user to avoid duplicates
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT test_name, status, due_date FROM reminders WHERE user_id = ? AND status IN ('pending', 'sent')",
        (user["user_id"],),
    )
    existing_reminders = [dict(r) for r in cursor.fetchall()]

    cursor.execute(
        "SELECT test_name, date, status FROM appointments WHERE user_id = ? AND status = 'confirmed'",
        (user["user_id"],),
    )
    existing_appointments = [dict(r) for r in cursor.fetchall()]
    conn.close()

    price_lines = []
    seen = set()
    for p in sorted(lab_prices, key=lambda x: x["price_inr"])[:50]:
        key = p["test_name"].upper()
        if key in seen:
            continue
        seen.add(key)
        price_lines.append(f"{p['test_name']} - Rs.{p['price_inr']} at {p['lab_name']}")

    system_prompt = """You are an autonomous Agentic Health Monitor for HealthGuardian AI.
You proactively analyze user health data and make INDEPENDENT decisions.
You do NOT wait for user input — you detect when checkups are due and ACT.

Your decisions must be based on:
- Medical history and chronic conditions
- Age-appropriate screenings
- Time since last checkup (if known)
- Seasonal/festival health context (Jaipur, India)
- Upcoming personal events (birthday, etc.)

You must return a JSON object with your autonomous decisions."""

    user_prompt = f"""Current date: {today_str}

USER PROFILE:
- Name: {user.get('name', 'User')}
- Age: {age} (DOB: {user.get('dob')})
- Marital Status: {user.get('marital_status', 'unknown')}
- Location: Jaipur, India
- Medical History: {history or 'No history available'}

EXISTING ACTIVE REMINDERS (avoid duplicates):
{json.dumps(existing_reminders, indent=2) if existing_reminders else 'None'}

EXISTING APPOINTMENTS:
{json.dumps(existing_appointments, indent=2) if existing_appointments else 'None'}

AVAILABLE TESTS & PRICES:
{chr(10).join(price_lines[:40])}

SEASONAL CONTEXT (Jaipur):
- Jan-Feb: Winter wellness checkups
- Mar-Apr: Holi/New Year health detox, summer prep
- Jun-Aug: Monsoon — dengue, malaria, infection screening
- Oct-Nov: Diwali — post-festival detox, immunity boost
- Dec: Year-end comprehensive health review

TASK — Act as an autonomous agent. Analyze the user profile and DECIDE:
1. Which health checkups are DUE or OVERDUE
2. What reminders to CREATE (with due dates)
3. What notifications to SEND right now
4. Your reasoning for each decision

Return ONLY valid JSON:
{{
  "agent_reasoning": "Brief explanation of your analysis and decisions",
  "reminders_to_create": [
    {{
      "test_name": "Test Name",
      "reason": "Why this is needed now",
      "trigger": "medical history|age|seasonal|birthday|overdue",
      "urgency": "this week|this month|next 3 months",
      "due_date": "YYYY-MM-DD"
    }}
  ],
  "notifications_to_send": [
    {{
      "channel": "push|sms|email|whatsapp",
      "title": "Notification title",
      "message": "Detailed notification message",
      "type": "reminder|urgent|info"
    }}
  ],
  "proactive_insight": "A personalized health insight message for the user"
}}"""

    try:
        client = get_azure_client()
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)
        return result

    except Exception as e:
        print(f"[Agent Monitor] Azure OpenAI error: {e}")
        return {
            "agent_reasoning": "Fallback: AI service unavailable. Generating default reminders.",
            "reminders_to_create": [
                {
                    "test_name": "Annual Health Checkup",
                    "reason": "Regular preventive screening recommended",
                    "trigger": "periodic",
                    "urgency": "this month",
                    "due_date": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
                }
            ],
            "notifications_to_send": [
                {
                    "channel": "push",
                    "title": "Health Checkup Reminder",
                    "message": f"Hi {user.get('name', 'there')}! Your annual health checkup is due. Book now for the best prices in Jaipur.",
                    "type": "reminder",
                }
            ],
            "proactive_insight": "Stay on top of your health with regular checkups!",
        }


def execute_agent_actions(user_id: str, agent_result: dict, user: dict = None) -> dict:
    """
    Execute the actions decided by the autonomous agent:
    - Create reminders in DB
    - Log notifications in DB
    - Record agent run
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    reminders_created = 0
    notifications_sent = 0

    # Create reminders
    for rem in agent_result.get("reminders_to_create", []):
        cursor.execute(
            """INSERT INTO reminders (user_id, test_name, reason, trigger, urgency, due_date, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                user_id,
                rem["test_name"],
                rem.get("reason", ""),
                rem.get("trigger", ""),
                rem.get("urgency", "this month"),
                rem.get("due_date", ""),
                now,
            ),
        )
        reminders_created += 1

    # Log notifications (simulated multi-channel)
    for notif in agent_result.get("notifications_to_send", []):
        cursor.execute(
            """INSERT INTO notifications (user_id, channel, title, message, type, sent_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                notif.get("channel", "push"),
                notif.get("title", "Health Reminder"),
                notif.get("message", ""),
                notif.get("type", "reminder"),
                now,
            ),
        )
        notifications_sent += 1

    # Log the agent run
    cursor.execute(
        """INSERT INTO agent_runs (user_id, action, reasoning, result, run_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            user_id,
            "health_monitor_scan",
            agent_result.get("agent_reasoning", ""),
            json.dumps(
                {
                    "reminders_created": reminders_created,
                    "notifications_sent": notifications_sent,
                }
            ),
            now,
        ),
    )

    conn.commit()
    conn.close()

    actions = {
        "reminders_created": reminders_created,
        "notifications_sent": notifications_sent,
    }

    # Send emails if user has an email address
    if user and user.get("email"):
        run_at = datetime.now().strftime("%d %B %Y, %I:%M %p")
        reminders = agent_result.get("reminders_to_create", [])
        insight   = agent_result.get("proactive_insight", "")

        if reminders:
            send_reminders_email(
                to_email=user["email"],
                user_name=user.get("name", "User"),
                reminders=reminders,
                insight=insight,
            )

        send_agent_activity_email(
            to_email=user["email"],
            user_name=user.get("name", "User"),
            agent_result=agent_result,
            actions=actions,
            run_at=run_at,
        )

    return actions
