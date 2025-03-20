from flask import Blueprint, render_template, redirect, url_for, request, flash, session, jsonify
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import uuid
import sqlite3
import os
import json
from functools import wraps
import re
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth")

def init_db():
    """Initialise la base de données avec le schéma et l'utilisateur admin"""
    logger.info("Début d'initialisation de la base de données")
    if not os.path.exists(DB_PATH):
        logger.info(f"Création du fichier {DB_PATH}")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Création des tables
        logger.info("Création du schéma de la base de données")
        cursor.execute(USER_SCHEMA)
        cursor.execute(NOTIFICATION_SCHEMA)
        
        # Vérification si l'utilisateur admin existe déjà
        admin_exists = cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'").fetchone()[0]
        logger.info(f'Vérification utilisateur admin: {"Existe" if admin_exists else "N\'existe pas"}')
        
        if not admin_exists:
            # Création de l'utilisateur admin par défaut
            logger.info("Création du compte admin par défaut")
            hashed_pwd = bcrypt.generate_password_hash('admin123').decode('utf-8')
            cursor.execute(
                'INSERT INTO users (username, email, password, role, api_key) VALUES (?, ?, ?, ?, ?)',
                ('admin', 'admin@pokemon-monitor.com', hashed_pwd, 'admin', str(uuid.uuid4()))
            )
        
        conn.commit()
        conn.close()
        logger.info("Initialisation de la base de données réussie")
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
        raise

# Initialisation
auth_bp = Blueprint('auth', __name__)
bcrypt = Bcrypt()

# Configuration des BD
DB_PATH = 'database.db'
USER_SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    role TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    api_key TEXT UNIQUE,
    preferences TEXT
)
'''

NOTIFICATION_SCHEMA = '''
CREATE TABLE IF NOT EXISTS user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    collection TEXT,
    product TEXT,
    site TEXT,
    min_price REAL,
    max_price REAL,
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
)
'''

def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(USER_SCHEMA)
        cursor.execute(NOTIFICATION_SCHEMA)
        
        # Créer un compte admin par défaut
        if not get_user_by_username('admin'):
            hashed_pwd = bcrypt.generate_password_hash('admin123').decode('utf-8')
            cursor.execute(
                'INSERT INTO users (username, email, password, role, api_key) VALUES (?, ?, ?, ?, ?)',
                ('admin', 'admin@pokemon-monitor.com', hashed_pwd, 'admin', str(uuid.uuid4()))
            )
        
        conn.commit()
        conn.close()

# Fonctions d'accès à la base de données
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_user_by_username(username):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return user

def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def get_pending_users():
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users WHERE role = "pending" ORDER BY created_at DESC').fetchall()
    conn.close()
    return users

def get_all_users():
    conn = get_db_connection()
    users = conn.execute('SELECT id, username, email, role, created_at, last_login FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return users

def create_user(username, email, password, first_name="", last_name="", role="pending"):
    conn = get_db_connection()
    api_key = str(uuid.uuid4())
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    
    try:
        conn.execute(
            'INSERT INTO users (username, email, password, first_name, last_name, role, api_key) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (username, email, hashed_password, first_name, last_name, role, api_key)
        )
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    finally:
        conn.close()
    
    return success

def update_user_role(user_id, new_role):
    conn = get_db_connection()
    conn.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    conn.commit()
    conn.close()
    return True

def update_user_last_login(user_id):
    conn = get_db_connection()
    conn.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def update_user_preferences(user_id, preferences):
    conn = get_db_connection()
    conn.execute('UPDATE users SET preferences = ? WHERE id = ?', (json.dumps(preferences), user_id))
    conn.commit()
    conn.close()

def get_user_preferences(user_id):
    conn = get_db_connection()
    prefs = conn.execute('SELECT preferences FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if prefs and prefs['preferences']:
        return json.loads(prefs['preferences'])
    return {}

def save_notification_preference(user_id, collection, product, site, min_price=0, max_price=9999):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO user_notifications (user_id, collection, product, site, min_price, max_price) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, collection, product, site, min_price, max_price)
    )
    conn.commit()
    conn.close()
    return True

def get_user_notifications(user_id):
    conn = get_db_connection()
    notifications = conn.execute(
        'SELECT * FROM user_notifications WHERE user_id = ? AND active = 1', 
        (user_id,)
    ).fetchall()
    conn.close()
    return notifications

# Validation des formulaires
def validate_registration(username, email, password, password_confirm):
    errors = []
    
    # Validation du nom d'utilisateur
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters")
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        errors.append("Username can only contain letters, numbers, underscores and hyphens")
    
    # Validation de l'email
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        errors.append("Valid email address required")
    
    # Validation du mot de passe
    if not password or len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password) or not re.search(r'[0-9]', password):
        errors.append("Password must contain uppercase, lowercase and numeric characters")
    
    # Confirmation du mot de passe
    if password != password_confirm:
        errors.append("Passwords do not match")
    
    # Vérification que l'utilisateur n'existe pas déjà
    if get_user_by_username(username):
        errors.append("Username already in use")
    if get_user_by_email(email):
        errors.append("Email already in use")
    
    return errors

# Décorateurs pour la protection des routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login', next=request.url))
        
        user = get_user_by_id(session['user_id'])
        if not user or user['role'] != 'admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('main.dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({'error': 'API key required'}), 401
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE api_key = ?', (api_key,)).fetchone()
        conn.close()
        
        if not user or user['role'] not in ['admin', 'user']:
            return jsonify({'error': 'Invalid API key'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

# Routes d'authentification
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        user = get_user_by_username(username)
        
        if user and bcrypt.check_password_hash(user['password'], password):
            if user['role'] == 'pending':
                flash('Your account is pending approval', 'warning')
                return redirect(url_for('auth.login'))
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            if remember:
                # Set session to last 30 days
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=30)
            
            update_user_last_login(user['id'])
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        
        errors = validate_registration(username, email, password, password_confirm)
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html', 
                                  username=username, 
                                  email=email,
                                  first_name=first_name,
                                  last_name=last_name)
        
        success = create_user(username, email, password, first_name, last_name)
        
        if success:
            flash('Registration successful! Your account is pending approval.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('An error occurred during registration', 'danger')
    
    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/profile')
@login_required
def profile():
    user = get_user_by_id(session['user_id'])
    user_prefs = get_user_preferences(session['user_id'])
    notifications = get_user_notifications(session['user_id'])
    
    return render_template('profile.html', user=user, preferences=user_prefs, notifications=notifications)

@auth_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    user_id = session['user_id']
    email = request.form.get('email')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    
    user = get_user_by_id(user_id)
    
    conn = get_db_connection()
    if email and email != user['email']:
        if get_user_by_email(email):
            flash('Email already in use', 'danger')
            return redirect(url_for('auth.profile'))
        conn.execute('UPDATE users SET email = ? WHERE id = ?', (email, user_id))
    
    if first_name:
        conn.execute('UPDATE users SET first_name = ? WHERE id = ?', (first_name, user_id))
    
    if last_name:
        conn.execute('UPDATE users SET last_name = ? WHERE id = ?', (last_name, user_id))
    
    if current_password and new_password:
        if bcrypt.check_password_hash(user['password'], current_password):
            if len(new_password) < 8:
                flash('New password must be at least 8 characters', 'danger')
                conn.close()
                return redirect(url_for('auth.profile'))
            
            hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, user_id))
            flash('Password updated', 'success')
        else:
            flash('Current password is incorrect', 'danger')
            conn.close()
            return redirect(url_for('auth.profile'))
    
    conn.commit()
    conn.close()
    
    flash('Profile updated successfully', 'success')
    return redirect(url_for('auth.profile'))

@auth_bp.route('/profile/preferences', methods=['POST'])
@login_required
def update_preferences():
    user_id = session['user_id']
    preferences = {
        'theme': request.form.get('theme', 'light'),
        'notifications_email': request.form.get('notifications_email') == 'on',
        'notifications_browser': request.form.get('notifications_browser') == 'on',
        'notifications_telegram': request.form.get('notifications_telegram') == 'on',
        'auto_refresh': request.form.get('auto_refresh') == 'on',
        'refresh_interval': int(request.form.get('refresh_interval', 60))
    }
    
    update_user_preferences(user_id, preferences)
    flash('Preferences updated', 'success')
    return redirect(url_for('auth.profile'))

@auth_bp.route('/profile/notifications', methods=['POST'])
@login_required
def add_notification():
    user_id = session['user_id']
    collection = request.form.get('collection')
    product = request.form.get('product', '')
    site = request.form.get('site', '')
    min_price = float(request.form.get('min_price', 0))
    max_price = float(request.form.get('max_price', 9999))
    
    save_notification_preference(user_id, collection, product, site, min_price, max_price)
    flash('Notification preference saved', 'success')
    return redirect(url_for('auth.profile'))

# Routes d'administration
@auth_bp.route('/admin')
@admin_required
def admin_dashboard():
    pending_users = get_pending_users()
    all_users = get_all_users()
    
    return render_template('admin/dashboard.html', 
                          pending_users=pending_users,
                          all_users=all_users)

@auth_bp.route('/admin/approve/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id):
    update_user_role(user_id, 'user')
    flash('User approved', 'success')
    return redirect(url_for('auth.admin_dashboard'))

@auth_bp.route('/admin/reject/<int:user_id>', methods=['POST'])
@admin_required
def reject_user(user_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    flash('User rejected', 'success')
    return redirect(url_for('auth.admin_dashboard'))

@auth_bp.route('/admin/change_role/<int:user_id>', methods=['POST'])
@admin_required
def change_role(user_id):
    new_role = request.form.get('role')
    if new_role not in ['admin', 'user', 'pending']:
        flash('Invalid role', 'danger')
        return redirect(url_for('auth.admin_dashboard'))
    
    update_user_role(user_id, new_role)
    flash('User role updated', 'success')
    return redirect(url_for('auth.admin_dashboard'))

# Initialisation de la base de données
init_db()
