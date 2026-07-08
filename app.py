from flask import Flask, render_template, request, jsonify
import os
from datetime import datetime

app = Flask(__name__)

# ─── DATABASE SETUP ──────────────────────────────────────────────────────────

def get_db():
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id          SERIAL PRIMARY KEY,
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

    c.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            rating     INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            comment    TEXT,
            photo_url  TEXT,
            approved   BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS profile (
            id       SERIAL PRIMARY KEY,
            bio      TEXT,
            photo_url TEXT,
            instagram TEXT,
            tiktok   TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Default settings
    c.execute("INSERT INTO settings VALUES ('start_hour', '10') ON CONFLICT (key) DO NOTHING")
    c.execute("INSERT INTO settings VALUES ('end_hour', '18') ON CONFLICT (key) DO NOTHING")
    c.execute("INSERT INTO settings VALUES ('available_dates', '') ON CONFLICT (key) DO NOTHING")
    c.execute("INSERT INTO settings VALUES ('location', 'Location TBD') ON CONFLICT (key) DO NOTHING")
    c.execute("INSERT INTO settings VALUES ('location_url', '') ON CONFLICT (key) DO NOTHING")

    # Default profile
    c.execute('''
        INSERT INTO profile (id, bio, photo_url, instagram, tiktok)
        VALUES (1, 'Your barber bio here...', '', '', '')
        ON CONFLICT (id) DO NOTHING
    ''')

    conn.commit()
    conn.close()

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_setting(key):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO settings VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s", (key, value, value))
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

@app.route('/reviews')
def reviews_page():
    return render_template('reviews.html')

@app.route('/profile')
def profile_page():
    return render_template('profile.html')

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify({
        'start_hour':      int(get_setting('start_hour') or 10),
        'end_hour':        int(get_setting('end_hour') or 18),
        'available_dates': get_available_dates(),
        'location':        get_setting('location') or 'Location TBA',
        'location_url':    get_setting('location_url') or ''
    })

@app.route('/api/slots', methods=['GET'])
def api_get_slots():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'No date provided'}), 400

    start = int(get_setting('start_hour') or 10)
    end   = int(get_setting('end_hour') or 18)

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT time FROM bookings WHERE date=%s AND status != 'cancelled'",
        (date,)
    )
    booked = c.fetchall()
    conn.close()

    booked_times = [row[0] for row in booked]

    all_slots = []
    for h in range(start, end):
        time_str = f"{h}:00"
        all_slots.append({
            'value':     time_str,
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

    if not all([name, phone, date, time]):
        return jsonify({'error': 'All fields required'}), 400

    available_dates = get_available_dates()
    if date not in available_dates:
        return jsonify({'error': 'Date not available'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM bookings WHERE date=%s AND time=%s AND status != 'cancelled'",
        (date, time)
    )
    conflict = c.fetchone()

    if conflict:
        conn.close()
        return jsonify({'error': 'Slot already taken'}), 409

    c.execute(
        "INSERT INTO bookings (name, phone, date, time) VALUES (%s,%s,%s,%s) RETURNING id",
        (name, phone, date, time)
    )
    booking_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    return jsonify({
        'success':    True,
        'booking_id': booking_id,
        'name':       name,
        'phone':      phone,
        'date':       date,
        'time':       time,
        'service':    'Haircut',
        'price':      10
    })

# ─── REVIEWS ROUTES ──────────────────────────────────────────────────────────

@app.route('/api/reviews', methods=['GET'])
def api_get_reviews():
    conn = get_db()
    c = conn.cursor()
    # Only return approved reviews to public
    c.execute('''
        SELECT id, name, rating, comment, photo_url, created_at
        FROM reviews
        WHERE approved = TRUE
        ORDER BY created_at DESC
    ''')
    rows = c.fetchall()
    cols = ['id', 'name', 'rating', 'comment', 'photo_url', 'created_at']
    conn.close()
    return jsonify([dict(zip(cols, row)) for row in rows])

@app.route('/api/reviews', methods=['POST'])
def api_submit_review():
    data = request.get_json()

    name    = data.get('name', '').strip()
    rating  = data.get('rating')
    comment = data.get('comment', '').strip()

    if not name or not rating:
        return jsonify({'error': 'Name and rating required'}), 400

    try:
        rating = int(rating)
        if not 1 <= rating <= 5:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'Rating must be 1-5'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''INSERT INTO reviews (name, rating, comment)
           VALUES (%s, %s, %s) RETURNING id''',
        (name, rating, comment)
    )
    review_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    return jsonify({
        'success':   True,
        'review_id': review_id,
        'message':   'Review submitted! Awaiting approval.'
    })

# ─── PROFILE ROUTES ───────────────────────────────────────────────────────────

@app.route('/api/profile', methods=['GET'])
def api_get_profile():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT bio, photo_url, instagram, tiktok FROM profile WHERE id=1')
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({
            'bio':       '',
            'photo_url': '',
            'instagram': '',
            'tiktok':    ''
        })

    return jsonify({
        'bio':       row[0] or '',
        'photo_url': row[1] or '',
        'instagram': row[2] or '',
        'tiktok':    row[3] or ''
    })

# ─── ADMIN ROUTES ─────────────────────────────────────────────────────────────

@app.route('/admin-lambocutz-secret')
def admin():
    return render_template('admin.html')

@app.route('/api/admin/bookings', methods=['GET'])
def api_admin_bookings():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM bookings ORDER BY date ASC, time ASC")
    rows = c.fetchall()
    cols = [desc[0] for desc in c.description]
    conn.close()
    return jsonify([dict(zip(cols, row)) for row in rows])

@app.route('/api/admin/booking/<int:booking_id>', methods=['PATCH'])
def api_update_booking(booking_id):
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()

    if 'status' in data:
        c.execute(
            "UPDATE bookings SET status=%s WHERE id=%s",
            (data['status'], booking_id)
        )
    if 'payment' in data:
        c.execute(
            "UPDATE bookings SET payment=%s WHERE id=%s",
            (data['payment'], booking_id)
        )

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/booking/<int:booking_id>', methods=['DELETE'])
def api_delete_booking(booking_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM bookings WHERE id=%s", (booking_id,))
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
    if 'location' in data:
        set_setting('location', data['location'])
    if 'location_url' in data:
        set_setting('location_url', data['location_url'])

    return jsonify({'success': True})

@app.route('/api/admin/reviews', methods=['GET'])
def api_admin_reviews():
    """Get ALL reviews including unapproved ones"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM reviews ORDER BY created_at DESC')
    rows = c.fetchall()
    cols = [desc[0] for desc in c.description]
    conn.close()
    return jsonify([dict(zip(cols, row)) for row in rows])

@app.route('/api/admin/reviews/<int:review_id>', methods=['PATCH'])
def api_admin_update_review(review_id):
    """Approve or reject a review"""
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()

    if 'approved' in data:
        c.execute(
            "UPDATE reviews SET approved=%s WHERE id=%s",
            (data['approved'], review_id)
        )

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/reviews/<int:review_id>', methods=['DELETE'])
def api_admin_delete_review(review_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM reviews WHERE id=%s", (review_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/profile', methods=['POST'])
def api_admin_save_profile():
    """Admin updates barber profile"""
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        UPDATE profile SET
            bio        = %s,
            photo_url  = %s,
            instagram  = %s,
            tiktok     = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    ''', (
        data.get('bio', ''),
        data.get('photo_url', ''),
        data.get('instagram', ''),
        data.get('tiktok', '')
    ))

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/clear', methods=['POST'])
def api_clear_bookings():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM bookings")
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── RUN ─────────────────────────────────────────────────────────────────────

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
