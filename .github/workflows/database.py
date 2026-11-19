import sqlite3
from datetime import datetime


def get_db_connection():
    conn = sqlite3.connect("lab_prices.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lab_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lab_name TEXT NOT NULL,
            city TEXT NOT NULL,
            test_name TEXT NOT NULL,
            price_inr INTEGER NOT NULL,
            has_offer BOOLEAN DEFAULT FALSE,
            offer_text TEXT,
            last_updated TEXT,
            UNIQUE(lab_name, city, test_name)
        )
    """
    )
    # User profile & history (for POC)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            dob DATE,
            marital_status TEXT,
            mobile TEXT,
            location TEXT DEFAULT "Jaipur",
            medical_history TEXT,
            last_recommendation TEXT,
            created_at TEXT
        )
    """
    )

    # Health checkup reminders — the agentic AI schedules these proactively
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            test_name TEXT NOT NULL,
            reason TEXT,
            trigger TEXT,
            urgency TEXT DEFAULT 'this month',
            due_date TEXT,
            status TEXT DEFAULT 'pending',
            channel TEXT DEFAULT 'push',
            created_at TEXT,
            notified_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """
    )

    # Appointments — booking simulation with slot selection
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            lab_name TEXT NOT NULL,
            test_name TEXT NOT NULL,
            date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            price_inr INTEGER,
            status TEXT DEFAULT 'confirmed',
            booked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """
    )

    # Notification log — multi-channel simulated notifications
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'reminder',
            sent_at TEXT,
            read_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """
    )

    # Agent run log — tracks autonomous monitoring decisions
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reasoning TEXT,
            result TEXT,
            run_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """
    )

    # Labs — diagnostic lab directory (dynamically managed)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            address TEXT,
            city TEXT DEFAULT 'Jaipur',
            phone TEXT,
            rating REAL DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            lat REAL,
            lng REAL,
            timings TEXT,
            accredited BOOLEAN DEFAULT FALSE,
            active BOOLEAN DEFAULT TRUE,
            created_at TEXT,
            updated_at TEXT
        )
    """
    )

    # nearby_labs — stores Mappls API results per user for email cross-matching
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nearby_labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            address TEXT,
            distance REAL,
            lat REAL,
            lng REAL,
            rating TEXT,
            open_now INTEGER DEFAULT 1,
            saved_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """
    )

    # Migrations — add columns if they don't exist yet
    for col, typedef in [("mobile", "TEXT"), ("email", "TEXT"), ("notified_at", "TEXT"), ("user_lat", "REAL"), ("user_lng", "REAL")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
        except Exception:
            pass

    # notified_at on reminders tracks which alert checkpoints have been sent
    try:
        cursor.execute("ALTER TABLE reminders ADD COLUMN notified_at TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


def seed_labs():
    """Seed initial lab data if the labs table is empty.
    In production this would come from an admin panel or external API."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM labs")
    if cursor.fetchone()["cnt"] > 0:
        conn.close()
        return

    now = datetime.now().isoformat()
    seed_data = [
        ("Dr B Lal Clinical Laboratory", "B-33, Surajpole Bazaar Road, Jaipur, Rajasthan 302003",
         "Jaipur", "+91-141-2561111", 4.3, 1250, 26.9196, 75.8235,
         "7:00 AM - 8:00 PM", True, True, now, now),
        ("Dr Lal PathLabs", "Shop 4-5, Ganpati Plaza, MI Road, Jaipur, Rajasthan 302001",
         "Jaipur", "+91-141-4041100", 4.1, 980, 26.9155, 75.8003,
         "7:30 AM - 7:30 PM", True, True, now, now),
        ("Redcliffe Labs", "D-42, Mahaveer Marg, C-Scheme, Jaipur, Rajasthan 302001",
         "Jaipur", "+91-8448-448-448", 4.5, 670, 26.9065, 75.7913,
         "6:30 AM - 9:00 PM", True, True, now, now),
    ]
    cursor.executemany(
        """INSERT INTO labs (name, address, city, phone, rating, review_count,
           lat, lng, timings, accredited, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        seed_data,
    )
    conn.commit()
    conn.close()
    print(f"[DB] Seeded {len(seed_data)} labs")
