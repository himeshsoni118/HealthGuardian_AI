import re
import sqlite3

DB_PATH = "lab_prices.db"


def clean_test_name(raw):
    # Take only the first line and collapse whitespace
    first_line = raw.strip().split('\n')[0].strip().upper()
    return re.sub(r'\s+', ' ', first_line)


conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT id, test_name FROM lab_prices")
rows = cursor.fetchall()

deleted = 0
updated = 0

for row_id, test_name in rows:
    cleaned = clean_test_name(test_name)

    if cleaned != test_name:
        # Check if cleaned name already exists for same lab+city to avoid unique constraint violation
        cursor.execute(
            "SELECT id FROM lab_prices WHERE test_name = ? AND lab_name = (SELECT lab_name FROM lab_prices WHERE id = ?) AND city = (SELECT city FROM lab_prices WHERE id = ?) AND id != ?",
            (cleaned, row_id, row_id, row_id)
        )
        if cursor.fetchone():
            cursor.execute("DELETE FROM lab_prices WHERE id = ?", (row_id,))
            print(f"  🗑  Deleted duplicate after clean: {repr(test_name[:60])}")
            deleted += 1
        else:
            cursor.execute("UPDATE lab_prices SET test_name = ? WHERE id = ?", (cleaned, row_id))
            print(f"  ✏️  Cleaned: {repr(test_name[:60])} → {repr(cleaned[:60])}")
            updated += 1

conn.commit()
conn.close()

print(f"\n✅ Done — {deleted} rows deleted, {updated} rows cleaned.")
