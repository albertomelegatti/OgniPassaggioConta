import os
import re
import time
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask.cli import load_dotenv
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
from werkzeug.security import generate_password_hash, check_password_hash
from admin import admin_bp

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

# Configurazione upload file
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

Session(app)

# Registra blueprints
app.register_blueprint(admin_bp)

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
                              maglia.id as maglia_id, maglia.titolo, maglia.descrizione, maglia.prezzo_base, maglia.sport, maglia.foto
                       FROM maglia
                       LEFT JOIN asta ON asta.id_maglia = maglia.id
                       WHERE maglia.sport = %s
                       ORDER BY asta.data_fine DESC NULLS LAST
                ''',(sport.lower(),))
        
        shirts_raw = cur.fetchall()
        
        # LEFT JOIN restituisce tutte le maglie, anche quelle senza asta (asta.id sarà None)
        
        for shirt in shirts_raw:
            # Parsa le foto: prova JSON, altrimenti virgola, altrimenti placeholder
            foto_list = []
            if shirt['foto']:
                try:
                    # Prova prima come array JSON
                    foto_list = json.loads(shirt['foto']) if isinstance(shirt['foto'], str) else shirt['foto']
                    # Rimuovi le virgolette doppie dai link (se presenti)
                    foto_list = [url.strip().strip('"') for url in foto_list]
                except (json.JSONDecodeError, TypeError):
                    # Se non è JSON valido, prova come stringa separata da virgole
                    try:
                        foto_list = [f.strip().strip('"') for f in shirt['foto'].split(',') if f.strip()]
                    except:
                        foto_list = []
            
            if not foto_list:
                foto_list = [f'https://via.placeholder.com/300x400?text={shirt["titolo"].replace(" ", "+")}']
            
            shirts.append({
                'id': shirt['id'],
                'maglia_id': shirt['maglia_id'],
                'title': shirt['titolo'],
                'base_price': shirt['prezzo_base'],
                'current_price': shirt['offerta_attuale'],
                'end_time': formatta_data(shirt['data_fine']),
                'current_winner': shirt['vincitore_attuale'],
                'has_auction': shirt['id'] is not None,
                'image': foto_list[0]  # Prima foto per la preview
            })
            
        
    except Exception as e:
        print(f"Error fetching shirts: {e}")
        
    finally:
        release_connection(conn, cur)
    
    return render_template('shirts.html', sport=sport, shirts=shirts)



@app.route('/shirt/<int:maglia_id>')
def shirt_detail(maglia_id):
    
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Fetch shirt details
        cur.execute('''
            SELECT asta.id, asta.data_inizio, asta.data_fine, asta.offerta_attuale, asta.vincitore_attuale, 
                   maglia.id as maglia_id, maglia.titolo, maglia.descrizione, maglia.prezzo_base, 
                   maglia.sport, maglia.foto
            FROM maglia
            LEFT JOIN asta ON asta.id_maglia = maglia.id
            WHERE maglia.id = %s
        ''', (maglia_id,))
        
        shirt_row = cur.fetchone()
        
        if not shirt_row:
            flash('Maglia non trovata', 'error')
            return redirect(url_for('sports'))
        
        shirt = {
            'maglia_id': shirt_row['maglia_id'],
            'id': shirt_row['id'],
            'athlete': shirt_row['titolo'],
            'description': shirt_row['descrizione'],
            'base_price': shirt_row['prezzo_base'],
            'current_price': shirt_row['offerta_attuale'],
            'end_time': formatta_data(shirt_row['data_fine']),
            'current_winner': shirt_row['vincitore_attuale'],
            'has_auction': shirt_row['id'] is not None,
            'sport': shirt_row['sport'],
            'images': []
        }
        
        # Parsa le foto dal database (formato JSON array, con fallback su virgole)
        if shirt_row['foto']:
            try:
                # Prova prima come array JSON
                shirt['images'] = json.loads(shirt_row['foto']) if isinstance(shirt_row['foto'], str) else shirt_row['foto']
                # Rimuovi le virgolette doppie dai link (se presenti)
                shirt['images'] = [url.strip().strip('"') for url in shirt['images']]
            except (json.JSONDecodeError, TypeError):
                # Se non è JSON valido, prova come stringa separata da virgole
                try:
                    shirt['images'] = [f.strip().strip('"') for f in shirt_row['foto'].split(',') if f.strip()]
                except:
                    shirt['images'] = []
        
        # Se non ci sono foto, usa placeholder
        if not shirt['images']:
            shirt['images'] = [f'https://via.placeholder.com/400x500?text={shirt_row["titolo"].replace(" ", "+")}']
        
    except Exception as e:
        print(f"Error fetching shirt details: {e}")
        flash('Errore nel caricamento della maglia', 'error')
        return redirect(url_for('sports'))
        
    finally:
        release_connection(conn, cur)
    
    return render_template('single_shirt.html', shirt=shirt)





@app.route('/offer/<int:asta_id>', methods=['POST'])
def make_offer(asta_id):
    
    if not session.get('user_id'):
        flash('Devi accedere per fare un\'offerta', 'error')
        return redirect(url_for('login'))
    
    try:
        offerta = float(request.form.get('offerta', 0))
        
        if offerta <= 0:
            flash('L\'offerta deve essere maggiore di 0', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verifica l'offerta attuale e data_fine
        cur.execute('SELECT offerta_attuale, data_fine FROM asta WHERE id = %s', (asta_id,))
        asta_data = cur.fetchone()
        
        if not asta_data:
            flash('Asta non trovata', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        offerta_attuale = asta_data['offerta_attuale'] or 0
        
        # L'offerta deve essere superiore di almeno 1€
        if offerta < offerta_attuale + 1:
            flash(f'L\'offerta deve essere almeno € {offerta_attuale + 1:.2f}', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        # Aggiorna l'offerta e la data_fine (estesa di 2 ore)
        cur.execute('''
            UPDATE asta 
            SET offerta_attuale = %s, vincitore_attuale = %s, data_fine = (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '2 hours'
            WHERE id = %s
        ''', (offerta, session.get('user_id'), asta_id))
        
        conn.commit()
        flash(f'Offerta di € {offerta:.2f} inviata con successo! Asta estesa di 2 ore.', 'success')
        
    except ValueError:
        flash('Importo non valido', 'error')
    except Exception as e:
        print(f"Error making offer: {e}")
        flash('Errore durante l\'invio dell\'offerta', 'error')
    finally:
        release_connection(conn, cur)
    
    return redirect(request.referrer or url_for('sports'))




@app.route('/start-auction/<int:maglia_id>', methods=['POST'])
def start_auction(maglia_id):
    
    if not session.get('user_id'):
        flash('Devi accedere per avviare un\'asta', 'error')
        return redirect(url_for('login'))
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verifica che la maglia esista
        cur.execute('SELECT id, titolo, prezzo_base FROM maglia WHERE id = %s', (maglia_id,))
        maglia = cur.fetchone()
        
        if not maglia:
            flash('Maglia non trovata', 'error')
            return redirect(url_for('sports'))
        
        # Verifica che non esista già un'asta per questa maglia
        cur.execute('SELECT id FROM asta WHERE id_maglia = %s', (maglia_id,))
        if cur.fetchone():
            flash(f'Un\'asta esiste già per la maglia "{maglia["titolo"]}"', 'warning')
            return redirect(request.referrer or url_for('sports'))
        
        # Crea una nuova asta: scadenza 2 ore da adesso (ora di Roma)
        cur.execute('''
            INSERT INTO asta (id_maglia, data_inizio, data_fine, offerta_attuale)
            VALUES (%s, NOW() AT TIME ZONE 'Europe/Rome', (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '2 hours', %s)
        ''', (maglia_id, maglia['prezzo_base']))
        
        conn.commit()
        flash(f'Asta avviata per "{maglia["titolo"]}" - Scade tra 2 ore', 'success')
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error starting auction: {e}")
        flash(f'Errore durante l\'avvio dell\'asta: {str(e)}', 'error')
    
    finally:
        release_connection(conn, cur)
    
    return redirect(request.referrer or url_for('sports'))





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
                SELECT username, hash_password, email, permessi
                FROM utente 
                WHERE username = %s
            ''', (username,))
            
            user = cur.fetchone()
            
            if user and check_password_hash(user['hash_password'], password):
                # Crea la sessione
                session['user_id'] = user['username']
                session['email'] = user['email']
                session['permessi'] = user['permessi']
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
                INSERT INTO utente (username, hash_password, email, permessi)
                VALUES (%s, %s, %s, %s)
            ''', (username, password_hash, email, 'base'))
            
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






def formatta_data(data_input):
    # Converte una data (stringa o datetime) in formato 'dd/mm/YYYY HH:MM'.
    # Rimuove automaticamente millisecondi e timezone.
    
    if data_input is None:
        return None

    # Se è una stringa ISO, puliscila
    if isinstance(data_input, str):
        # Rimuove millisecondi e timezone se presenti
        data_input = data_input.split("+")[0].split("Z")[0].split(".")[0]
        try:
            data_input = datetime.fromisoformat(data_input)
        except ValueError:
            return data_input  # se non è una data ISO valida, restituisci com'è

    # Se è un oggetto datetime, formatta
    if isinstance(data_input, datetime):
        return data_input.strftime("%d/%m/%Y %H:%M")

    return str(data_input)


@app.route('/health')
def health():
    return {'status': 'ok'}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
