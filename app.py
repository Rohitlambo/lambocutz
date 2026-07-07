from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DB = 'database.db'

# ─── DATABASE SETUP ──────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            phone       TEXT NOT NULL,
            date        TEXT NOT NULL,
            time        TEXT NOT NULL,
            service     TEXT DEFAULT 'Haircut',
            price       INTEGER DEFAULT 10,
            payment     TEXT DEFAULT 'unpaid',
            status      TEXT DEFAULT 'confirmed',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Default settings
    c.execute("INSERT OR IGNORE INTO settings VALUES ('start_hour', '10')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('end_hour', '18')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('available_dates', '')")

    conn.commit()
    conn.close()

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def get_available_dates():
    raw = get_setting('available_dates')
    if not raw:
        return []
    return [d for d in raw.split(',') if d]

# ─── CUSTOMER ROUTES ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify({
        'start_hour': int(get_setting('start_hour') or 10),
        'end_hour':   int(get_setting('end_hour') or 18),
        'available_dates': get_available_dates()
    })

@app.route('/api/slots', methods=['GET'])
def api_get_slots():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'No date provided'}), 400

    start = int(get_setting('start_hour') or 10)
    end   = int(get_setting('end_hour') or 18)

    # Get booked slots for this date
    conn = get_db()
    booked = conn.execute(
        "SELECT time FROM bookings WHERE date=? AND status != 'cancelled'",
        (date,)
    ).fetchall()
    conn.close()

    booked_times = [row['time'] for row in booked]

    all_slots = []
    for h in range(start, end):
        time_str = f"{h}:00"
        all_slots.append({
            'value': time_str,
            'available': time_str not in booked_times
        })

    return jsonify({'slots': all_slots})

@app.route('/api/book', methods=['POST'])
def api_book():
    data = request.get_json()

    name  = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    date  = data.get('date', '').strip()
    time  = data.get('time', '').strip()

    # Validation
    if not all([name, phone, date, time]):
        return jsonify({'error': 'All fields required'}), 400

    # Check date is available
    available_dates = get_available_dates()
    if date not in available_dates:
        return jsonify({'error': 'Date not available'}), 400

    # Check slot not taken
    conn = get_db()
    conflict = conn.execute(
        "SELECT id FROM bookings WHERE date=? AND time=? AND status != 'cancelled'",
        (date, time)
    ).fetchone()

    if conflict:
        conn.close()
        return jsonify({'error': 'Slot already taken'}), 409

    # Insert booking
    cursor = conn.execute(
        "INSERT INTO bookings (name, phone, date, time) VALUES (?,?,?,?)",
        (name, phone, date, time)
    )
    booking_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'booking_id': booking_id,
        'name': name,
        'phone': phone,
        'date': date,
        'time': time,
        'service': 'Haircut',
        'price': 10
    })

# ─── ADMIN ROUTES ─────────────────────────────────────────────────────────────

@app.route('/admin-lambocutz-secret')
def admin():
    return render_template('admin.html')

@app.route('/api/admin/bookings', methods=['GET'])
def api_admin_bookings():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookings ORDER BY date ASC, time ASC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/booking/<int:booking_id>', methods=['PATCH'])
def api_update_booking(booking_id):
    data = request.get_json()
    conn = get_db()

    if 'status' in data:
        conn.execute(
            "UPDATE bookings SET status=? WHERE id=?",
            (data['status'], booking_id)
        )

    if 'payment' in data:
        conn.execute(
            "UPDATE bookings SET payment=? WHERE id=?",
            (data['payment'], booking_id)
        )

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/booking/<int:booking_id>', methods=['DELETE'])
def api_delete_booking(booking_id):
    conn = get_db()
    conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/settings', methods=['POST'])
def api_save_settings():
    data = request.get_json()

    if 'start_hour' in data:
        set_setting('start_hour', str(data['start_hour']))
    if 'end_hour' in data:
        set_setting('end_hour', str(data['end_hour']))
    if 'available_dates' in data:
        set_setting('available_dates', ','.join(data['available_dates']))

    return jsonify({'success': True})

@app.route('/api/admin/clear', methods=['POST'])
def api_clear_bookings():
    conn = get_db()
    conn.execute("DELETE FROM bookings")
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── RUN ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
