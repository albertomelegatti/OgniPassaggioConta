import os
import re
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from flask.cli import load_dotenv
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from whitenoise import WhiteNoise
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
from werkzeug.security import generate_password_hash, check_password_hash
from admin import admin_bp
from utils import email_bp, init_email, parse_foto_urls, get_paypal_payment_link

load_dotenv()
init_pool()

# Configure Flask with explicit paths for static and template folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, static_folder=STATIC_FOLDER)
app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_FOLDER, prefix="static/")

is_production = bool(os.getenv("RENDER_DEPLOYMENT_ID"))

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    if is_production:
        raise RuntimeError(
            "SECRET_KEY non impostata: obbligatoria in produzione (Render). "
            "Imposta la variabile d'ambiente SECRET_KEY prima di avviare l'app."
        )
    secret_key = "chiave_segreta_default_per_sviluppo"
app.secret_key = secret_key

db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if db_url and db_url.startswith("postgresql://"):
    # Forza esplicitamente il driver psycopg2 (quello usato anche da db.py):
    # senza questo, SQLAlchemy puo' auto-selezionare il driver psycopg (v3),
    # non installato, e far crashare l'app all'avvio.
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'max_overflow': 2,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
    'pool_timeout': 10,
}

db = SQLAlchemy(app)

redis_url = os.getenv("REDIS_URL")
if redis_url:
    import redis
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
else:
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

init_email(app)

app.register_blueprint(admin_bp)
app.register_blueprint(email_bp)

csrf = CSRFProtect(app)
# Il blueprint email espone un webhook chiamato da Supabase (server-to-server,
# nessuna sessione browser): non ha senso applicargli la protezione CSRF.
csrf.exempt(email_bp)


@app.before_request
def start_request_timer():
    g.request_start = time.perf_counter()


@app.after_request
def log_slow_requests(response):
    start = getattr(g, "request_start", None)
    if start:
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        slow_request_ms = float(os.getenv("SLOW_REQUEST_MS", "1000"))
        if duration_ms > slow_request_ms:
            app.logger.warning(
                "[SLOW REQUEST] %s %s -> %s in %.1fms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )
    return response

# Crea la tabella delle sessioni al primo avvio
with app.app_context():
    db.create_all()


@app.route('/')
def landing():
    return render_template('index.html', username=session.get('username'))
 


@app.route('/sports')
def sports():
        return render_template('sports.html', username=session.get('username'))


@app.route('/shirts/<sport>')
def shirts(sport):
        
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    shirts = []
    try:
        cur.execute('''
                       SELECT asta.id, asta.data_inizio, asta.data_fine, asta.offerta_attuale, asta.vincitore_attuale, asta.stato, 
                              maglia.id as maglia_id, maglia.titolo, maglia.descrizione, maglia.prezzo_base, maglia.sport, maglia.foto
                       FROM maglia
                       LEFT JOIN asta ON asta.id_maglia = maglia.id
                       WHERE maglia.sport = %s
                       ORDER BY asta.data_fine DESC NULLS LAST
                ''',(sport.lower(),))
        
        shirts_raw = cur.fetchall()
        
        # LEFT JOIN restituisce tutte le maglie, anche quelle senza asta (asta.id sarà None)
        
        for shirt in shirts_raw:
            # Parsa foto
            foto_list = parse_foto_urls(shirt['foto'], shirt['titolo'])
            
            # Controlla lo stato dell'asta
            auction_ended = False
            if shirt['id'] is not None and shirt['stato'] is not None:
                if shirt['stato'] == 'conclusa':
                    auction_ended = True
            
            shirts.append({
                'id': shirt['id'],
                'maglia_id': shirt['maglia_id'],
                'title': shirt['titolo'],
                'base_price': to_float(shirt['prezzo_base']),
                'current_price': to_float(shirt['offerta_attuale']),
                'end_time': formatta_data(shirt['data_fine']),
                'current_winner': shirt['vincitore_attuale'],
                'has_auction': shirt['id'] is not None,
                'auction_ended': auction_ended,
                'image': foto_list[0]  # Prima foto per la preview
            })
            
        
    except Exception:
        app.logger.exception("Errore nel caricamento delle maglie per sport=%s", sport)
    finally:
        release_connection(conn, cur)

    return render_template('shirts.html', sport=sport, shirts=shirts, username=session.get('username'))





@app.route('/shirt/<int:maglia_id>')
def shirt_detail(maglia_id):
    
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Fetch shirt details
        cur.execute('''
            SELECT asta.id, asta.data_inizio, asta.data_fine, asta.offerta_attuale, asta.vincitore_attuale, asta.stato, 
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
            'base_price': to_float(shirt_row['prezzo_base']),
            'current_price': to_float(shirt_row['offerta_attuale']),
            'end_time': formatta_data(shirt_row['data_fine']),
            'current_winner': shirt_row['vincitore_attuale'],
            'has_auction': shirt_row['id'] is not None,
            'sport': shirt_row['sport'],
            'images': parse_foto_urls(shirt_row['foto'], shirt_row['titolo']),
            'auction_ended': shirt_row['id'] is not None and shirt_row['stato'] == 'conclusa'
        }

        is_winner = (
            shirt['auction_ended']
            and shirt['current_winner'] is not None
            and shirt['current_winner'] == session.get('username')
        )
        shirt['paypal_link'] = get_paypal_payment_link(shirt['current_price']) if is_winner else None
        
    except Exception:
        app.logger.exception("Errore nel caricamento della maglia maglia_id=%s", maglia_id)
        flash('Errore nel caricamento della maglia', 'error')
        return redirect(url_for('sports'))

    finally:
        release_connection(conn, cur)
    
    return render_template('single_shirt.html', shirt=shirt, username=session.get('username'))





@app.route('/api/asta/<int:asta_id>')
def get_auction_data(asta_id):
    
    # Endpoint API che restituisce i dati aggiornati dell'asta in JSON
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT offerta_attuale, vincitore_attuale, data_fine, stato
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
            'minimo_offerta': float(asta['offerta_attuale']) + 1 if asta['offerta_attuale'] else 1,
            'stato': asta['stato']
        })
        
    except Exception:
        app.logger.exception("Errore nel recupero dati asta_id=%s", asta_id)
        return jsonify({'error': 'Errore nel recupero dati'}), 500
    finally:
        release_connection(conn, cur)


@app.route('/offer/<int:asta_id>', methods=['POST'])
def make_offer(asta_id):
    
    if not session.get('logged_in'):
        flash('Devi accedere per fare un\'offerta', 'error')
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
                data_fine = CASE 
                    WHEN data_fine <= (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '5 minutes'
                    THEN data_fine + INTERVAL '10 minutes'
                    ELSE data_fine
                END
            WHERE id = %s 
                AND stato = 'in_corso' 
                AND (%s >= offerta_attuale + 1)
            RETURNING offerta_attuale, data_fine
        ''', (offerta, session.get('username'), asta_id, offerta))
        
        updated_auction = cur.fetchone()
        
        if not updated_auction:
            # Recupera il valore attuale e lo stato per il messaggio d'errore
            cur.execute('SELECT offerta_attuale, stato FROM asta WHERE id = %s', (asta_id,))
            asta_data = cur.fetchone()
            
            if not asta_data:
                flash('Asta non trovata', 'error')
            elif asta_data['stato'] == 'conclusa':
                flash('Questa asta è già conclusa', 'error')
            else:
                offerta_attuale = asta_data['offerta_attuale']
                flash(f'L\'offerta deve essere almeno € {offerta_attuale + 1:.2f}', 'error')
            return redirect(request.referrer or url_for('sports'))
        
        conn.commit()
        flash(f'Offerta di € {offerta:.2f} inviata con successo!', 'success')
        
    except ValueError:
        flash('Importo non valido', 'error')
    except Exception:
        app.logger.exception("Errore durante l'invio dell'offerta asta_id=%s", asta_id)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        flash('Errore durante l\'invio dell\'offerta', 'error')
    finally:
        release_connection(conn, cur)
    
    return redirect(request.referrer or url_for('sports'))




@app.route('/start-auction/<int:maglia_id>', methods=['POST'])
def start_auction(maglia_id):
    
    if not session.get('logged_in'):
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
        
        # Verifica se esiste già un'asta per questa maglia
        cur.execute('SELECT id FROM asta WHERE id_maglia = %s', (maglia_id,))
        asta_esistente = cur.fetchone()
        
        if asta_esistente:
            flash(f'Un\'asta esiste già per la maglia "{maglia["titolo"]}"', 'warning')
            return redirect(request.referrer or url_for('sports'))
        
        # Se non esiste, crea la nuova asta
        try:
            cur.execute('''
                INSERT INTO asta (id_maglia, data_inizio, data_fine, offerta_attuale, stato, vincitore_attuale)
                VALUES (
                    %s,
                    NOW() AT TIME ZONE 'Europe/Rome',
                    CASE
                        WHEN (NOW() AT TIME ZONE 'Europe/Rome') < (DATE_TRUNC('day', NOW() AT TIME ZONE 'Europe/Rome') + TIME '20:00')
                        THEN (DATE_TRUNC('day', NOW() AT TIME ZONE 'Europe/Rome') + TIME '20:00')
                        ELSE (DATE_TRUNC('day', NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '1 day' + TIME '20:00')
                    END,
                    %s,
                    'in_corso',
                    %s
                )
                RETURNING id
            ''', (maglia_id, maglia['prezzo_base'], session.get('username')))
            
            result = cur.fetchone()
            conn.commit()
            flash(f'Asta avviata per "{maglia["titolo"]}" - Scade alle 20:00', 'success')
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise
        
    except Exception as e:
        app.logger.exception("Errore durante l'avvio dell'asta maglia_id=%s", maglia_id)
        if conn:
            try:
                conn.rollback()
            except:
                pass
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
            flash('Compila username e password', 'error')
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
                session.clear()
                session['logged_in'] = True
                session['username'] = user['username']
                session['email'] = user['email']
                session['permessi'] = user['permessi']
                session.permanent = True
                
                flash('Login avvenuto con successo!', 'success')
                return redirect(url_for('landing'))
            else:
                flash('Credenziali non valide. Riprova.', 'error')
        
        except Exception:
            app.logger.exception("Errore di connessione al database durante il login")
            flash(' Errore di connessione al database.', 'error')

        finally:
            release_connection(conn, cur)
        
        return redirect(url_for('login'))
    
    return render_template('login.html', username=session.get('username'))


@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('landing'))


@app.route('/account')
def account():
    # Verifica che l'utente sia loggato
    if not session.get('logged_in'):
        flash('Devi accedere per visualizzare il tuo account', 'error')
        return redirect(url_for('login'))
    
    conn = None
    cur = None
    won_auctions = []
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recupera tutte le aste vinte dall'utente (concluse e con vincitore_attuale = username)
        cur.execute('''
            SELECT asta.id, asta.data_fine, asta.offerta_attuale, 
                   maglia.id as maglia_id, maglia.titolo, maglia.descrizione, 
                   maglia.sport, maglia.foto
            FROM asta
            JOIN maglia ON asta.id_maglia = maglia.id
            WHERE asta.vincitore_attuale = %s
            AND asta.stato = 'conclusa'
            ORDER BY asta.data_fine DESC
        ''', (session.get('username'),))
        
        auctions_raw = cur.fetchall()
        
        for auction in auctions_raw:
            foto_list = parse_foto_urls(auction['foto'], auction['titolo'])
            won_auctions.append({
                'id': auction['id'],
                'maglia_id': auction['maglia_id'],
                'title': auction['titolo'],
                'description': auction['descrizione'],
                'final_price': to_float(auction['offerta_attuale']),
                'end_time': formatta_data(auction['data_fine']),
                'sport': auction['sport'],
                'image': foto_list[0],  # Prima foto
                'paypal_link': get_paypal_payment_link(auction['offerta_attuale'])
            })
        
    except Exception:
        app.logger.exception("Errore nel caricamento delle aste vinte per username=%s", session.get('username'))
        flash('Errore nel caricamento delle aste vinte', 'error')

    finally:
        release_connection(conn, cur)
    
    return render_template('user.html', won_auctions=won_auctions, username=session.get('username'))






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
            return render_template('signup.html', error=' | '.join(errors), username=session.get('username'))
        
        conn = None
        cur = None
        try:
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
                    return render_template('signup.html', error='Email già in uso', username=session.get('username'))
                elif 'username' in str(e).lower():
                    return render_template('signup.html', error='Username già in uso', username=session.get('username'))
                else:
                    raise
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            app.logger.exception("Error during signup")
            flash('Errore durante la registrazione. Riprova più tardi.', 'error')
            return render_template('signup.html', username=session.get('username'))
        
        finally:
            release_connection(conn, cur)
    
    return render_template('signup.html', username=session.get('username'))


@app.route('/change-password', methods=['GET', 'POST'])
def change_password_page():
    # Verifica che l'utente sia loggato
    if not session.get('logged_in'):
        flash('Devi accedere per cambiare la password', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validazione
        if not current_password or not new_password or not confirm_password:
            return render_template('change_password.html', error='Compila tutti i campi', username=session.get('username'))
        
        if new_password != confirm_password:
            return render_template('change_password.html', error='Le password non corrispondono', username=session.get('username'))
        
        if len(new_password) < 6:
            return render_template('change_password.html', error='La password deve avere almeno 6 caratteri', username=session.get('username'))
        
        conn = None
        cur = None
        
        try:
            conn = get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Recupera la password hash dell'utente
            cur.execute('''
                SELECT hash_password FROM utente WHERE username = %s
            ''', (session.get('username'),))
            
            user = cur.fetchone()
            
            if not user:
                return render_template('change_password.html', error='Utente non trovato', username=session.get('username'))
            
            # Verifica che la password attuale sia corretta
            if not check_password_hash(user['hash_password'], current_password):
                return render_template('change_password.html', error='Password attuale non corretta', username=session.get('username'))
            
            # Genera il nuovo hash della password
            new_password_hash = generate_password_hash(new_password)
            
            # Aggiorna la password nel database
            cur.execute('''
                UPDATE utente SET hash_password = %s WHERE username = %s
            ''', (new_password_hash, session.get('username')))
            
            conn.commit()
            
            flash('Password aggiornata con successo!', 'success')
            return redirect(url_for('account'))
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            app.logger.exception("Error during password change")
            return render_template('change_password.html', error='Errore durante il cambio password', username=session.get('username'))
        
        finally:
            release_connection(conn, cur)
    
    return render_template('change_password.html', username=session.get('username'))


@app.route('/change-password-api', methods=['POST'])
@csrf.exempt
def change_password_api():
    # Verifica che l'utente sia loggato
    if not session.get('logged_in'):
        return jsonify({'error': 'Non sei loggato'}), 401
    
    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Compila tutti i campi'}), 400
    
    if len(new_password) < 6:
        return jsonify({'error': 'La password deve avere almeno 6 caratteri'}), 400
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recupera la password hash dell'utente
        cur.execute('''
            SELECT hash_password FROM utente WHERE username = %s
        ''', (session.get('username'),))
        
        user = cur.fetchone()
        
        if not user:
            return jsonify({'error': 'Utente non trovato'}), 404
        
        # Verifica che la password attuale sia corretta
        if not check_password_hash(user['hash_password'], current_password):
            return jsonify({'error': 'Password attuale non corretta'}), 401
        
        # Genera il nuovo hash della password
        new_password_hash = generate_password_hash(new_password)
        
        # Aggiorna la password nel database
        cur.execute('''
            UPDATE utente SET hash_password = %s WHERE username = %s
        ''', (new_password_hash, session.get('username')))
        
        conn.commit()
        
        return jsonify({'success': 'Password aggiornata con successo'}), 200
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        app.logger.exception("Error during password change (API)")
        return jsonify({'error': 'Errore durante il cambio password'}), 500
    
    finally:
        release_connection(conn, cur)




def to_float(value):
    # Converte Decimal/None in float, cosi' i template possono fare aritmetica
    # (es. current_price + 1.00) senza il TypeError Decimal+float di Python.
    return float(value) if value is not None else None


def formatta_data(data_input):
    # Converte una data (stringa o datetime) in formato 'dd/mm/YYYY HH:MM'.
    # Rimuove automaticamente millisecondi e timezone.
    
    if data_input is None:
        return None

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


@app.route('/coffee')
def coffee():
    return render_template('coffee.html', username=session.get('username'))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=not is_production)
