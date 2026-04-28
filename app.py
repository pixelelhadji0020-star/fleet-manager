import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, jsonify, send_from_directory)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fleet-secret-2025')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

DATABASE = os.path.join(os.path.dirname(__file__), 'instance', 'fleet.db')

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        phone TEXT,
        role TEXT NOT NULL DEFAULT 'client',
        doc_status TEXT NOT NULL DEFAULT 'aucun',
        doc_permis TEXT,
        doc_cni TEXT,
        doc_justif TEXT,
        doc_submitted_at TEXT,
        doc_validated_at TEXT,
        doc_validator TEXT,
        doc_reject_reason TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        plate TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,
        year INTEGER,
        color TEXT,
        seats INTEGER DEFAULT 5,
        fuel TEXT DEFAULT 'Essence',
        transmission TEXT DEFAULT 'Manuelle',
        price_per_day REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'disponible',
        image TEXT,
        description TEXT,
        mileage INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        date_start TEXT NOT NULL,
        date_end TEXT NOT NULL,
        total_price REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'en_attente',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reservation_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'en_attente',
        paid_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (reservation_id) REFERENCES reservations(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reservation_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        comfort_note INTEGER,
        cleanliness_note INTEGER,
        reliability_note INTEGER,
        service_note INTEGER,
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (reservation_id) REFERENCES reservations(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT DEFAULT 'info',
        read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # Seed admin
    admin_exists = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not admin_exists:
        db.execute("""INSERT INTO users (email,password_hash,first_name,last_name,role,doc_status)
            VALUES (?,?,?,?,?,?)""",
            ('admin@fleet.com', generate_password_hash('admin123'),
             'Admin', 'Flotte', 'admin', 'approuve'))

    # Seed vehicles
    vehicles_exist = db.execute("SELECT id FROM vehicles").fetchone()
    if not vehicles_exist:
        vehicles = [
            ('Renault', 'Clio 5', 'AB-123-CD', 'Citadine', 2022, 'Rouge', 5, 'Essence', 'Manuelle', 29475.0, 'disponible', 'clio.jpg', 'Citadine économique parfaite pour la ville.', 12000),
            ('Peugeot', '3008 GT', 'EF-456-GH', 'SUV', 2023, 'Gris', 5, 'Diesel', 'Automatique', 58295.0, 'disponible', 'peugeot.jpg', 'SUV premium avec finitions haut de gamme.', 8500),
            ('Volkswagen', 'Golf 8', 'IJ-789-KL', 'Berline', 2022, 'Noir', 5, 'Essence', 'Manuelle', 40610.0, 'disponible', 'golf.jpg', 'Berline polyvalente, confort et fiabilité.', 15000),
            ('Mercedes', 'Classe A', 'MN-012-OP', 'Luxe', 2023, 'Blanc', 5, 'Essence', 'Automatique', 85150.0, 'disponible', 'mercedes.jpg', 'Expérience de conduite premium.', 6000),
            ('Citroën', 'Berlingo', 'QR-345-ST', 'Utilitaire', 2021, 'Blanc', 7, 'Diesel', 'Manuelle', 45850.0, 'disponible', 'berlingo.jpg', 'Spacieux, idéal pour les familles et transports.', 22000),
            ('BMW', 'Série 3', 'UV-678-WX', 'Luxe', 2023, 'Bleu', 5, 'Diesel', 'Automatique', 75325.0, 'disponible', 'bmw.jpg', 'La référence des berlines sportives premium.', 9000),
            ('Toyota', 'Yaris', 'YZ-901-AB', 'Citadine', 2022, 'Vert', 5, 'Hybride', 'Automatique', 34060.0, 'disponible', 'yaris.jpg', 'Hybride économique, faible consommation.', 18000),
            ('Ford', 'Puma', 'CD-234-EF', 'SUV', 2021, 'Orange', 5, 'Essence', 'Manuelle', 44540.0, 'louee', 'puma.jpg', 'SUV compact dynamique au style affirmé.', 20000),
        ]
        db.executemany("""INSERT INTO vehicles
            (brand,model,plate,category,year,color,seats,fuel,transmission,price_per_day,status,image,description,mileage)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", vehicles)

    db.commit()
    db.close()

# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Accès réservé aux administrateurs.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_user():
    if 'user_id' not in session:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()

def add_notification(user_id, title, message, notif_type='info'):
    get_db().execute(
        "INSERT INTO notifications (user_id,title,message,type) VALUES (?,?,?,?)",
        (user_id, title, message, notif_type))
    get_db().commit()

# ─────────────────────────────────────────────
# PUBLIC ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    db = get_db()
    vehicles = db.execute("""
        SELECT v.*,
            ROUND(AVG((r.comfort_note+r.cleanliness_note+r.reliability_note+r.service_note)/4.0),1) as avg_note,
            COUNT(DISTINCT res.id) as total_rentals
        FROM vehicles v
        LEFT JOIN reviews r ON r.vehicle_id = v.id
        LEFT JOIN reservations res ON res.vehicle_id = v.id AND res.status = 'terminee'
        GROUP BY v.id
        ORDER BY total_rentals DESC
        LIMIT 6
    """).fetchall()
    stats = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM vehicles WHERE status='disponible') as dispo,
            (SELECT COUNT(*) FROM users WHERE role='client') as clients,
            (SELECT COUNT(*) FROM reservations WHERE status='terminee') as locations
    """).fetchone()
    return render_template('index.html', vehicles=vehicles, stats=stats)

@app.route('/catalogue')
def catalogue():
    db = get_db()
    category = request.args.get('category', '')
    fuel = request.args.get('fuel', '')
    max_price = request.args.get('max_price', '')
    date_start = request.args.get('date_start', '')
    date_end = request.args.get('date_end', '')

    query = """
        SELECT v.*,
            ROUND(AVG((r.comfort_note+r.cleanliness_note+r.reliability_note+r.service_note)/4.0),1) as avg_note,
            COUNT(DISTINCT rev.id) as total_rentals
        FROM vehicles v
        LEFT JOIN reviews r ON r.vehicle_id = v.id
        LEFT JOIN reservations rev ON rev.vehicle_id = v.id AND rev.status='terminee'
        WHERE 1=1
    """
    params = []
    if category:
        query += " AND v.category=?"; params.append(category)
    if fuel:
        query += " AND v.fuel=?"; params.append(fuel)
    if max_price:
        query += " AND v.price_per_day<=?"; params.append(float(max_price))
    if date_start and date_end:
        query += """
            AND v.id NOT IN (
                SELECT vehicle_id FROM reservations
                WHERE status NOT IN ('annulee','refusee')
                AND date_start <= ? AND date_end >= ?
            )
        """
        params += [date_end, date_start]
    else:
        query += " AND v.status != 'hors_service'"

    query += " GROUP BY v.id ORDER BY v.price_per_day"
    vehicles = db.execute(query, params).fetchall()
    categories = db.execute("SELECT DISTINCT category FROM vehicles ORDER BY category").fetchall()
    fuels = db.execute("SELECT DISTINCT fuel FROM vehicles ORDER BY fuel").fetchall()
    return render_template('catalogue.html', vehicles=vehicles, categories=categories,
                           fuels=fuels, filters={'category': category, 'fuel': fuel,
                           'max_price': max_price, 'date_start': date_start, 'date_end': date_end})

@app.route('/vehicule/<int:vid>')
def vehicle_detail(vid):
    db = get_db()
    v = db.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        flash('Véhicule introuvable.', 'error'); return redirect(url_for('catalogue'))
    reviews = db.execute("""
        SELECT r.*, u.first_name, u.last_name
        FROM reviews r JOIN users u ON u.id=r.user_id
        WHERE r.vehicle_id=? ORDER BY r.created_at DESC LIMIT 10
    """, (vid,)).fetchall()
    avg = db.execute("""
        SELECT ROUND(AVG((comfort_note+cleanliness_note+reliability_note+service_note)/4.0),1) as avg_note,
               COUNT(*) as total
        FROM reviews WHERE vehicle_id=?
    """, (vid,)).fetchone()
    return render_template('vehicle_detail.html', vehicle=v, reviews=reviews, avg=avg)

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route('/inscription', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        db = get_db()
        email = request.form['email'].strip().lower()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash('Cet e-mail est déjà utilisé.', 'error')
            return render_template('register.html')
        db.execute("""INSERT INTO users (email,password_hash,first_name,last_name,phone,role)
            VALUES (?,?,?,?,?,?)""",
            (email, generate_password_hash(request.form['password']),
             request.form['first_name'].strip(), request.form['last_name'].strip(),
             request.form.get('phone','').strip(), 'client'))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        session['user_id'] = user['id']
        session['role'] = 'client'
        session['name'] = user['first_name']
        add_notification(user['id'], 'Bienvenue !',
            'Votre compte a été créé. Déposez vos documents pour pouvoir réserver.', 'info')
        flash('Compte créé avec succès ! Déposez vos documents pour réserver.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/connexion', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        email = request.form['email'].strip().lower()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user['password_hash'], request.form['password']):
            flash('Email ou mot de passe incorrect.', 'error')
            return render_template('login.html')
        session['user_id'] = user['id']
        session['role'] = user['role']
        session['name'] = user['first_name']
        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/deconnexion')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ─────────────────────────────────────────────
# CLIENT PORTAL
# ─────────────────────────────────────────────

@app.route('/espace-client')
@login_required
def dashboard():
    db = get_db()
    user = get_current_user()
    reservations = db.execute("""
        SELECT r.*, v.brand, v.model, v.plate, v.price_per_day, v.image,
               i.status as invoice_status, i.id as invoice_id
        FROM reservations r
        JOIN vehicles v ON v.id=r.vehicle_id
        LEFT JOIN invoices i ON i.reservation_id=r.id
        WHERE r.user_id=? ORDER BY r.created_at DESC
    """, (user['id'],)).fetchall()
    notifs = db.execute("""
        SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 10
    """, (user['id'],)).fetchall()
    unread = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0",
                        (user['id'],)).fetchone()['c']
    return render_template('dashboard.html', user=user, reservations=reservations,
                           notifs=notifs, unread=unread)

@app.route('/documents', methods=['GET','POST'])
@login_required
def upload_documents():
    db = get_db()
    user = get_current_user()
    if request.method == 'POST':
        updates = {}
        for field in ['permis', 'cni', 'justif']:
            f = request.files.get(field)
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit('.', 1)[1].lower()
                fname = secure_filename(f"doc_{user['id']}_{field}_{int(datetime.now().timestamp())}.{ext}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                updates[f'doc_{field}'] = fname

        if updates:
            set_clause = ', '.join(f"{k}=?" for k in updates)
            vals = list(updates.values())
            if all(db.execute("SELECT doc_permis, doc_cni, doc_justif FROM users WHERE id=?",
                              (user['id'],)).fetchone()[f] or updates.get(f'doc_{f.split("_",1)[1]}')
                   for f in ['doc_permis', 'doc_cni', 'doc_justif']):
                set_clause += ', doc_status=?, doc_submitted_at=?'
                vals += ['en_attente', datetime.now().isoformat()]
            db.execute(f"UPDATE users SET {set_clause} WHERE id=?", vals + [user['id']])
            db.commit()

            # notify admins
            admins = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
            for adm in admins:
                add_notification(adm['id'], 'Nouveau dépôt documentaire',
                    f"{user['first_name']} {user['last_name']} a déposé ses documents. Vérification requise.", 'warning')

            flash('Documents envoyés avec succès ! En attente de validation.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Veuillez sélectionner au moins un fichier valide (PDF, JPG, PNG).', 'error')

    return render_template('upload_documents.html', user=user)

@app.route('/reserver/<int:vid>', methods=['GET','POST'])
@login_required
def reserve(vid):
    db = get_db()
    user = get_current_user()
    if user['doc_status'] != 'approuve':
        flash('Vos documents doivent être approuvés avant de réserver.', 'error')
        return redirect(url_for('upload_documents'))
    vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not vehicle:
        flash('Véhicule introuvable.', 'error'); return redirect(url_for('catalogue'))

    if request.method == 'POST':
        date_start = request.form['date_start']
        date_end = request.form['date_end']
        ds = date.fromisoformat(date_start)
        de = date.fromisoformat(date_end)
        if de <= ds:
            flash('La date de fin doit être après la date de début.', 'error')
        else:
            conflict = db.execute("""
                SELECT id FROM reservations
                WHERE vehicle_id=? AND status NOT IN ('annulee','refusee')
                AND date_start <= ? AND date_end >= ?
            """, (vid, date_end, date_start)).fetchone()
            if conflict:
                flash('Ce véhicule n\'est pas disponible sur cette période.', 'error')
            else:
                days = (de - ds).days
                total = days * vehicle['price_per_day']
                res_id = db.execute("""
                    INSERT INTO reservations (user_id,vehicle_id,date_start,date_end,total_price,status,notes)
                    VALUES (?,?,?,?,?,?,?)
                """, (user['id'], vid, date_start, date_end, total, 'en_attente',
                      request.form.get('notes',''))).lastrowid
                db.commit()
                add_notification(user['id'], 'Réservation reçue',
                    f'Votre demande pour {vehicle["brand"]} {vehicle["model"]} a été transmise.', 'info')
                admins = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
                for adm in admins:
                    add_notification(adm['id'], 'Nouvelle réservation',
                        f'{user["first_name"]} {user["last_name"]} — {vehicle["brand"]} {vehicle["model"]} du {date_start} au {date_end}', 'info')
                flash('Réservation soumise avec succès !', 'success')
                return redirect(url_for('dashboard'))

    return render_template('reserve.html', vehicle=vehicle, user=user)

@app.route('/annuler-reservation/<int:rid>', methods=['POST'])
@login_required
def cancel_reservation(rid):
    db = get_db()
    user = get_current_user()
    res = db.execute("SELECT * FROM reservations WHERE id=? AND user_id=?", (rid, user['id'])).fetchone()
    if res and res['status'] in ('en_attente', 'confirmee'):
        db.execute("UPDATE reservations SET status='annulee' WHERE id=?", (rid,))
        db.commit()
        flash('Réservation annulée.', 'success')
    else:
        flash('Impossible d\'annuler cette réservation.', 'error')
    return redirect(url_for('dashboard'))

@app.route('/avis/<int:rid>', methods=['GET','POST'])
@login_required
def leave_review(rid):
    db = get_db()
    user = get_current_user()
    res = db.execute("""SELECT r.*, v.brand, v.model FROM reservations r
        JOIN vehicles v ON v.id=r.vehicle_id
        WHERE r.id=? AND r.user_id=? AND r.status='terminee'""", (rid, user['id'])).fetchone()
    if not res:
        flash('Réservation introuvable ou non terminée.', 'error')
        return redirect(url_for('dashboard'))
    existing = db.execute("SELECT id FROM reviews WHERE reservation_id=?", (rid,)).fetchone()
    if existing:
        flash('Vous avez déjà laissé un avis pour cette location.', 'info')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        db.execute("""INSERT INTO reviews
            (reservation_id,user_id,vehicle_id,comfort_note,cleanliness_note,reliability_note,service_note,comment)
            VALUES (?,?,?,?,?,?,?,?)""",
            (rid, user['id'], res['vehicle_id'],
             int(request.form.get('comfort_note',5)),
             int(request.form.get('cleanliness_note',5)),
             int(request.form.get('reliability_note',5)),
             int(request.form.get('service_note',5)),
             request.form.get('comment','')))
        db.commit()
        flash('Merci pour votre avis !', 'success')
        return redirect(url_for('dashboard'))
    return render_template('review.html', reservation=res)

@app.route('/notifications/lues', methods=['POST'])
@login_required
def mark_notifications_read():
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (session['user_id'],))
    db.commit()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    stats = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM users WHERE role='client') as total_clients,
            (SELECT COUNT(*) FROM users WHERE role='client' AND doc_status='en_attente') as docs_pending,
            (SELECT COUNT(*) FROM vehicles) as total_vehicles,
            (SELECT COUNT(*) FROM vehicles WHERE status='disponible') as vehicles_dispo,
            (SELECT COUNT(*) FROM reservations WHERE status='en_attente') as reservations_pending,
            (SELECT COUNT(*) FROM reservations WHERE status='confirmee') as reservations_active,
            (SELECT ROUND(SUM(total_price),2) FROM reservations WHERE status='terminee') as total_revenue,
            (SELECT COUNT(*) FROM reservations WHERE status='terminee') as total_completed
    """).fetchone()
    recent_res = db.execute("""
        SELECT r.*, u.first_name, u.last_name, v.brand, v.model
        FROM reservations r
        JOIN users u ON u.id=r.user_id
        JOIN vehicles v ON v.id=r.vehicle_id
        ORDER BY r.created_at DESC LIMIT 8
    """).fetchall()
    pending_docs = db.execute("""
        SELECT * FROM users WHERE doc_status='en_attente' ORDER BY doc_submitted_at DESC
    """).fetchall()
    notifs = db.execute("""
        SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 10
    """, (session['user_id'],)).fetchall()
    unread = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0",
                        (session['user_id'],)).fetchone()['c']
    return render_template('admin/dashboard.html', stats=stats, recent_res=recent_res,
                           pending_docs=pending_docs, notifs=notifs, unread=unread)

@app.route('/admin/clients')
@admin_required
def admin_clients():
    db = get_db()
    status_filter = request.args.get('status', '')
    query = "SELECT * FROM users WHERE role='client'"
    params = []
    if status_filter:
        query += " AND doc_status=?"; params.append(status_filter)
    query += " ORDER BY created_at DESC"
    clients = db.execute(query, params).fetchall()
    return render_template('admin/clients.html', clients=clients, status_filter=status_filter)

@app.route('/admin/client/<int:uid>')
@admin_required
def admin_client_detail(uid):
    db = get_db()
    client = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not client:
        flash('Client introuvable.', 'error'); return redirect(url_for('admin_clients'))
    reservations = db.execute("""
        SELECT r.*, v.brand, v.model FROM reservations r
        JOIN vehicles v ON v.id=r.vehicle_id
        WHERE r.user_id=? ORDER BY r.created_at DESC
    """, (uid,)).fetchall()
    return render_template('admin/client_detail.html', client=client, reservations=reservations)

@app.route('/admin/valider-documents/<int:uid>', methods=['POST'])
@admin_required
def validate_documents(uid):
    db = get_db()
    action = request.form.get('action')
    reason = request.form.get('reason', '')
    admin = get_current_user()
    if action == 'approve':
        db.execute("""UPDATE users SET doc_status='approuve',
            doc_validated_at=?, doc_validator=?, doc_reject_reason=NULL
            WHERE id=?""",
            (datetime.now().isoformat(), f"{admin['first_name']} {admin['last_name']}", uid))
        add_notification(uid, 'Documents approuvés ✓',
            'Vos documents ont été validés. Vous pouvez maintenant réserver un véhicule !', 'success')
        flash('Documents approuvés.', 'success')
    elif action == 'reject':
        db.execute("""UPDATE users SET doc_status='rejete',
            doc_validated_at=?, doc_validator=?, doc_reject_reason=?
            WHERE id=?""",
            (datetime.now().isoformat(), f"{admin['first_name']} {admin['last_name']}", reason, uid))
        add_notification(uid, 'Documents refusés',
            f'Vos documents n\'ont pas été acceptés. Motif : {reason}. Veuillez les re-soumettre.', 'error')
        flash('Documents refusés.', 'warning')
    db.commit()
    return redirect(url_for('admin_client_detail', uid=uid))

@app.route('/admin/reservations')
@admin_required
def admin_reservations():
    db = get_db()
    status_filter = request.args.get('status', '')
    query = """
        SELECT r.*, u.first_name, u.last_name, u.email,
               v.brand, v.model, v.plate, v.price_per_day
        FROM reservations r
        JOIN users u ON u.id=r.user_id
        JOIN vehicles v ON v.id=r.vehicle_id
        WHERE 1=1
    """
    params = []
    if status_filter:
        query += " AND r.status=?"; params.append(status_filter)
    query += " ORDER BY r.created_at DESC"
    reservations = db.execute(query, params).fetchall()
    return render_template('admin/reservations.html', reservations=reservations, status_filter=status_filter)

@app.route('/admin/reservation/<int:rid>/action', methods=['POST'])
@admin_required
def admin_reservation_action(rid):
    db = get_db()
    action = request.form.get('action')
    res = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    if not res:
        flash('Réservation introuvable.', 'error'); return redirect(url_for('admin_reservations'))

    status_map = {
        'confirmer': 'confirmee',
        'refuser': 'refusee',
        'terminer': 'terminee',
        'annuler': 'annulee'
    }
    new_status = status_map.get(action)
    if new_status:
        db.execute("UPDATE reservations SET status=? WHERE id=?", (new_status, rid))
        if new_status == 'terminee':
            db.execute("""INSERT INTO invoices (reservation_id, user_id, amount, status)
                VALUES (?,?,?,?)""", (rid, res['user_id'], res['total_price'], 'emise'))
            add_notification(res['user_id'], 'Location terminée — Facture disponible',
                'Votre location est terminée. Merci de laisser un avis !', 'success')
        elif new_status == 'confirmee':
            add_notification(res['user_id'], 'Réservation confirmée ✓',
                'Votre réservation a été confirmée. Bonne route !', 'success')
        elif new_status == 'refusee':
            add_notification(res['user_id'], 'Réservation refusée',
                'Votre réservation n\'a pas pu être confirmée. Contactez l\'agence.', 'error')
        db.commit()
        flash(f'Réservation mise à jour : {new_status}.', 'success')
    return redirect(url_for('admin_reservations'))

@app.route('/admin/vehicules')
@admin_required
def admin_vehicles():
    db = get_db()
    vehicles = db.execute("""
        SELECT v.*,
            COUNT(DISTINCT r.id) as total_rentals,
            ROUND(AVG((rev.comfort_note+rev.cleanliness_note+rev.reliability_note+rev.service_note)/4.0),1) as avg_note,
            ROUND(SUM(r.total_price),2) as revenue
        FROM vehicles v
        LEFT JOIN reservations r ON r.vehicle_id=v.id AND r.status='terminee'
        LEFT JOIN reviews rev ON rev.vehicle_id=v.id
        GROUP BY v.id ORDER BY total_rentals DESC
    """).fetchall()
    return render_template('admin/vehicles.html', vehicles=vehicles)

@app.route('/admin/vehicule/ajouter', methods=['GET','POST'])
@admin_required
def admin_add_vehicle():
    if request.method == 'POST':
        db = get_db()
        image_filename = None
        f = request.files.get('image')
        if f and f.filename and allowed_file(f.filename):
            ext = f.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"vehicle_{int(datetime.now().timestamp())}.{ext}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        db.execute("""INSERT INTO vehicles
            (brand,model,plate,category,year,color,seats,fuel,transmission,
             price_per_day,description,status,image,mileage)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (request.form['brand'], request.form['model'], request.form['plate'],
             request.form['category'], int(request.form['year']), request.form['color'],
             int(request.form.get('seats',5)), request.form['fuel'], request.form['transmission'],
             float(request.form['price_per_day']), request.form.get('description',''),
             request.form.get('status','disponible'), image_filename,
             int(request.form.get('mileage',0))))
        db.commit()
        flash('Véhicule ajouté avec succès.', 'success')
        return redirect(url_for('admin_vehicles'))
    return render_template('admin/vehicle_form.html', vehicle=None)

@app.route('/admin/vehicule/<int:vid>/modifier', methods=['GET','POST'])
@admin_required
def admin_edit_vehicle(vid):
    db = get_db()
    vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not vehicle:
        flash('Véhicule introuvable.', 'error'); return redirect(url_for('admin_vehicles'))
    if request.method == 'POST':
        image_filename = vehicle['image']
        f = request.files.get('image')
        if f and f.filename and allowed_file(f.filename):
            ext = f.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"vehicle_{vid}_{int(datetime.now().timestamp())}.{ext}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        db.execute("""UPDATE vehicles SET brand=?,model=?,plate=?,category=?,year=?,color=?,
            seats=?,fuel=?,transmission=?,price_per_day=?,description=?,status=?,
            image=?,mileage=? WHERE id=?""",
            (request.form['brand'], request.form['model'], request.form['plate'],
             request.form['category'], int(request.form['year']), request.form['color'],
             int(request.form.get('seats',5)), request.form['fuel'], request.form['transmission'],
             float(request.form['price_per_day']), request.form.get('description',''),
             request.form.get('status','disponible'), image_filename,
             int(request.form.get('mileage',0)), vid))
        db.commit()
        flash('Véhicule modifié avec succès.', 'success')
        return redirect(url_for('admin_vehicles'))
    return render_template('admin/vehicle_form.html', vehicle=vehicle)

@app.route('/admin/statistiques')
@admin_required
def admin_stats():
    db = get_db()
    # Revenue by month (last 6)
    revenue_monthly = db.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               ROUND(SUM(total_price),2) as revenue,
               COUNT(*) as count
        FROM reservations WHERE status='terminee'
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()
    # Top vehicles
    top_vehicles = db.execute("""
        SELECT v.brand, v.model, v.category,
               COUNT(r.id) as rentals,
               ROUND(SUM(r.total_price),2) as revenue,
               ROUND(AVG((rev.comfort_note+rev.cleanliness_note+rev.reliability_note+rev.service_note)/4.0),1) as avg_note
        FROM vehicles v
        LEFT JOIN reservations r ON r.vehicle_id=v.id AND r.status='terminee'
        LEFT JOIN reviews rev ON rev.vehicle_id=v.id
        GROUP BY v.id ORDER BY rentals DESC LIMIT 8
    """).fetchall()
    # Utilisation rate
    utilization = db.execute("""
        SELECT v.brand, v.model, v.plate,
               COUNT(r.id) as rentals,
               ROUND(SUM(julianday(r.date_end)-julianday(r.date_start)),0) as days_rented
        FROM vehicles v
        LEFT JOIN reservations r ON r.vehicle_id=v.id AND r.status='terminee'
        GROUP BY v.id ORDER BY days_rented DESC
    """).fetchall()
    # Category breakdown
    by_category = db.execute("""
        SELECT v.category,
               COUNT(r.id) as rentals,
               ROUND(SUM(r.total_price),2) as revenue
        FROM vehicles v
        LEFT JOIN reservations r ON r.vehicle_id=v.id AND r.status='terminee'
        GROUP BY v.category
    """).fetchall()
    # Satisfaction
    satisfaction = db.execute("""
        SELECT v.brand, v.model,
               ROUND(AVG(r.comfort_note),1) as comfort,
               ROUND(AVG(r.cleanliness_note),1) as cleanliness,
               ROUND(AVG(r.reliability_note),1) as reliability,
               ROUND(AVG(r.service_note),1) as service,
               COUNT(*) as total_reviews
        FROM reviews r JOIN vehicles v ON v.id=r.vehicle_id
        GROUP BY r.vehicle_id ORDER BY total_reviews DESC
    """).fetchall()
    return render_template('admin/stats.html',
        revenue_monthly=revenue_monthly, top_vehicles=top_vehicles,
        utilization=utilization, by_category=by_category, satisfaction=satisfaction)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n" + "="*55)
    print("  🚗  FLEET MANAGER — Plateforme de Location")
    print("="*55)
    print("  URL : http://localhost:5000")
    print("  Admin : admin@fleet.com / admin123")
    print("="*55 + "\n")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
