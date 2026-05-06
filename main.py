import os
import re
import time
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
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
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24 * 30  # 30 giorni
app.config['SESSION_COOKIE_SECURE'] = True
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





@app.route('/api/asta/<int:asta_id>')
def get_auction_data(asta_id):
    """Endpoint API che restituisce i dati aggiornati dell'asta in JSON"""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT offerta_attuale, vincitore_attuale, data_fine
            FROM asta
            WHERE id = %s
        ''', (asta_id,))
        
        asta = cur.fetchone()
        
        if not asta:
            return jsonify({'error': 'Asta non trovata'}), 404
        
        return jsonify({
            'offerta_attuale': float(asta['offerta_attuale']) if asta['offerta_attuale'] else 0,
            'vincitore_attuale': asta['vincitore_attuale'],
            'data_fine': asta['data_fine'].isoformat() if asta['data_fine'] else None,
            'minimo_offerta': float(asta['offerta_attuale']) + 1 if asta['offerta_attuale'] else 1
        })
        
    except Exception as e:
        print(f"Error fetching auction data: {e}")
        return jsonify({'error': 'Errore nel recupero dati'}), 500
    finally:
        release_connection(conn, cur)


@app.route('/offer/<int:asta_id>', methods=['POST'])
def make_offer(asta_id):
    
    if not session.get('logged_in'):
        flash('❌ Devi accedere per fare un\'offerta', 'error')
        return redirect(url_for('login'))
    
    conn = None
    cur = None
    try:
        offerta = float(request.form.get('offerta', 0))
        
        if offerta <= 0:
            flash('L\'offerta deve essere maggiore di 0', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # ATOMICA: Verifica e aggiorna in un'unica query con lock pessimistico
        cur.execute('''
            UPDATE asta 
            SET offerta_attuale = %s, vincitore_attuale = %s, 
                data_fine = (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '2 hours'
            WHERE id = %s AND (%s >= COALESCE(offerta_attuale, 0) + 1)
            RETURNING offerta_attuale, data_fine
        ''', (offerta, session.get('username'), asta_id, offerta))
        
        updated_auction = cur.fetchone()
        
        if not updated_auction:
            # Recupera il valore attuale per il messaggio d'errore
            cur.execute('SELECT COALESCE(offerta_attuale, 0) as offerta_attuale FROM asta WHERE id = %s', (asta_id,))
            asta_data = cur.fetchone()
            
            if not asta_data:
                flash('Asta non trovata', 'error')
            else:
                offerta_attuale = asta_data['offerta_attuale']
                flash(f'L\'offerta deve essere almeno € {offerta_attuale + 1:.2f}', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        conn.commit()
        flash(f'Offerta di € {offerta:.2f} inviata con successo! Asta estesa di 2 ore.', 'success')
        
    except ValueError:
        flash('Importo non valido', 'error')
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error making offer: {e}")
        flash('Errore durante l\'invio dell\'offerta', 'error')
    finally:
        release_connection(conn, cur)
    
    return redirect(request.referrer or url_for('sports'))




@app.route('/start-auction/<int:maglia_id>', methods=['POST'])
def start_auction(maglia_id):
    
    if not session.get('logged_in'):
        flash('❌ Devi accedere per avviare un\'asta', 'error')
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
        
        # Tenta di inserire atomicamente - se già esiste, avrà errore
        try:
            cur.execute('''
                INSERT INTO asta (id_maglia, data_inizio, data_fine, offerta_attuale)
                VALUES (%s, NOW() AT TIME ZONE 'Europe/Rome', (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '2 hours', %s)
                ON CONFLICT (id_maglia) DO NOTHING
                RETURNING id
            ''', (maglia_id, maglia['prezzo_base']))
            
            result = cur.fetchone()
            
            if not result:
                # Un'asta esiste già per questa maglia
                flash(f'Un\'asta esiste già per la maglia "{maglia["titolo"]}"', 'warning')
                return redirect(request.referrer or url_for('sports'))
            
            conn.commit()
            flash(f'Asta avviata per "{maglia["titolo"]}" - Scade tra 2 ore', 'success')
            
        except Exception as e:
            if conn:
                conn.rollback()
            if 'unique' in str(e).lower():
                flash(f'Un\'asta esiste già per la maglia "{maglia["titolo"]}"', 'warning')
            else:
                raise
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error starting auction: {e}")
        flash(f'Errore durante l\'avvio dell\'asta: {str(e)}', 'error')
    
    finally:
        release_connection(conn, cur)
    
    return redirect(request.referrer or url_for('sports'))





@app.route('/login', methods=['GET', 'POST'])
def login():
    
    # Se l'utente è già loggato, reindirizza
    if session.get('logged_in'):
        return redirect(url_for('landing'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        # Validazione campi
        if not username or not password:
            flash('❌ Compila username e password', 'error')
            return redirect(url_for('login'))
        
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
                # Prepara la sessione (Flask-Session la salva automaticamente)
                session.clear()
                session['logged_in'] = True
                session['username'] = user['username']
                session['email'] = user['email']
                session['permessi'] = user['permessi']
                session.permanent = True
                
                flash('✅ Login avvenuto con successo!', 'success')
                return redirect(url_for('landing'))
            else:
                flash('❌ Credenziali non valide. Riprova.', 'error')
        
        except Exception as e:
            print(f"Error during login: {e}")
            flash('❌ Errore di connessione al database.', 'error')
            
        finally:
            release_connection(conn, cur)
        
        return redirect(url_for('login'))
    
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
            # Hash della password
            password_hash = generate_password_hash(password)
            
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Tenta di inserire atomicamente - se email/username esistono, avrà errore UNIQUE
            try:
                cur.execute('''
                    INSERT INTO utente (username, hash_password, email, permessi)
                    VALUES (%s, %s, %s, %s)
                    RETURNING username
                ''', (username, password_hash, email, 'base'))
                
                conn.commit()
                flash('Registrazione avvenuta con successo! Puoi ora effettuare il login.', 'success')
                return redirect(url_for('login'))
                
            except Exception as e:
                if conn:
                    conn.rollback()
                # Controlla quale vincolo UNIQUE è stato violato
                if 'email' in str(e).lower():
                    return render_template('signup.html', error='Email già in uso')
                elif 'username' in str(e).lower():
                    return render_template('signup.html', error='Username già in uso')
                else:
                    raise
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
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
