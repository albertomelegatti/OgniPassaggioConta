import os
import re
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask.cli import load_dotenv
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
init_pool()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "chiave_segreta_default_per_sviluppo")

# Determina se siamo in produzione (Render ha RENDER_DEPLOYMENT_ID)
is_production = bool(os.getenv("RENDER_DEPLOYMENT_ID"))

# Converte postgres:// in postgresql:// (per Supabase)
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}

db = SQLAlchemy(app)

app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24 * 365
app.config['SESSION_COOKIE_SECURE'] = is_production  # True solo in produzione (HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

Session(app)

# Crea la tabella delle sessioni al primo avvio
with app.app_context():
    db.create_all()



@app.route('/')
def landing():
    return render_template('index.html')


@app.route('/sports')
def sports():
    return render_template('sports.html')


@app.route('/shirts/<sport>')
def shirts(sport):
        
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    shirts = []
    try:
        cur.execute('''
                       SELECT asta.id, asta.data_inizio, asta.data_fine, asta.offerta_attuale, asta.vincitore_attuale, 
                              maglia.id as maglia_id, maglia.titolo, maglia.descrizione, maglia.prezzo_base, maglia.sport
                       FROM maglia
                       LEFT JOIN asta ON asta.id_maglia = maglia.id
                       WHERE maglia.sport = %s
                       ORDER BY asta.data_fine DESC NULLS LAST
                ''',(sport.lower(),))
        
        shirts_raw = cur.fetchall()
        
        for shirt in shirts_raw:
            shirts.append({
                'id': shirt['id'],
                'maglia_id': shirt['maglia_id'],
                'athlete': shirt['titolo'],
                # 'description': shirt['descrizione'],
                'base_price': shirt['prezzo_base'],
                'current_price': shirt['offerta_attuale'],
                # 'start_time': shirt['data_inizio'],
                'end_time': shirt['data_fine'],
                'current_winner': shirt['vincitore_attuale'],
                'has_auction': shirt['id'] is not None
            })
            
        
    except Exception as e:
        print(f"Error fetching shirts: {e}")
        
    finally:
        release_connection(conn, cur)
    
    return render_template('shirts.html', sport=sport, shirts=shirts)










@app.route('/login', methods=['GET', 'POST'])
def login():
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute('''
                SELECT username, hash_password, email 
                FROM utente 
                WHERE username = %s
            ''', (username,))
            
            user = cur.fetchone()
            
            if user and check_password_hash(user['hash_password'], password):
                # Crea la sessione
                session['user_id'] = user['username']
                session['email'] = user['email']
                session.permanent = True
                
                flash('Login avvenuto con successo!', 'success')
                return redirect(url_for('landing'))
            else:
                return render_template('login.html', error='Credenziali non valide. Riprova.')
        
        except Exception as e:
            print(f"Error during login: {e}")
            return render_template('login.html', error='Errore durante il login. Riprova più tardi.')
            
        finally:
            release_connection(conn, cur)
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('landing'))

















@app.route('/signup', methods=['GET', 'POST'])
def signup():
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        
        errors = []
        
        if not username or len(username) < 3:
            errors.append("Username deve essere almeno 3 caratteri")
        
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            errors.append("Email non valida")
        
        if not password or len(password) < 8:
            errors.append("Password deve essere almeno 8 caratteri")
        
        if password != password_confirm:
            errors.append("Le password non corrispondono")
        
        if errors:
            return render_template('signup.html', error=' | '.join(errors))
        
        
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Controlla se l'utente esiste già
            cur.execute('SELECT 1 FROM utente WHERE email = %s OR username = %s', (email, username))
            if cur.fetchone():
                return render_template('signup.html', error='Email o username già in uso')
                
            
            # Hash della password
            password_hash = generate_password_hash(password)
            
            # Inserisci il nuovo utente
            cur.execute('''
                INSERT INTO utente (username, hash_password, email)
                VALUES (%s, %s, %s)
            ''', (username, password_hash, email))
            
            conn.commit()
            
            
            flash('Registrazione avvenuta con successo! Puoi ora effettuare il login.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            if conn:
                conn.rollback()
            print(f"Error during signup: {e}")
            flash('Errore durante la registrazione. Riprova più tardi.', 'error')
            return render_template('signup.html')
        
        finally:
            release_connection(conn, cur)
    
    return render_template('signup.html')


@app.route('/admin')
def admin_dashboard():
    return render_template('admin.html')


@app.route('/health')
def health():
    return {'status': 'ok'}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
