import os
import re
from flask import Flask, render_template, request, redirect, url_for, flash
from flask.cli import load_dotenv
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
init_pool()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')



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










@app.route('/login')
def login():
    return render_template('login.html')




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
