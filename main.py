import os
import re
import time
import json
import traceback
import logging
import sys
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask.cli import load_dotenv
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
from werkzeug.security import generate_password_hash, check_password_hash
from admin import admin_bp
from utils import email_bp, init_email, parse_foto_urls

# WhiteNoise for serving static files in production
try:
    from whitenoise import WhiteNoise
    WHITENOISE_AVAILABLE = True
except ImportError:
    WHITENOISE_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

load_dotenv()

try:
    init_pool()
except Exception as e:
    logger.error(f"Failed to initialize database pool: {e}")
    logger.error(traceback.format_exc())
    sys.exit(1)

# Configure Flask with explicit paths for static and template folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.secret_key = os.getenv("SECRET_KEY", "chiave_segreta_default_per_sviluppo")

is_production = bool(os.getenv("RENDER_DEPLOYMENT_ID"))

db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
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

# Configure WhiteNoise for serving static files in production
if WHITENOISE_AVAILABLE:
    app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_FOLDER, index_file=False)
else:
    logger.warning("WhiteNoise not available, static files may not be served correctly on Render")

init_email(app)

app.register_blueprint(admin_bp)
app.register_blueprint(email_bp)

# Crea la tabella delle sessioni al primo avvio
with app.app_context():
    db.create_all()
    logger.info("✅ Database tables created/verified")

# ===== ERROR HANDLERS =====

@app.errorhandler(404)
def not_found(error):
    logger.warning(f"404 Not Found: {request.method} {request.path}")
    logger.warning(f"Referrer: {request.referrer}")
    logger.warning(f"User-Agent: {request.user_agent}")
    
    # Se è una richiesta HTML, ritorna messaggio di errore
    if request.accept_mimetypes.best == 'text/html':
        return {
            'error': 'Route not found',
            'path': request.path,
            'method': request.method,
            'available_routes': list(app.url_map.iter_rules()),
        }, 404
    
    return jsonify({'error': 'Route not found', 'path': request.path}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Internal Server Error: {error}")
    logger.error(traceback.format_exc())
    return jsonify({'error': 'Internal server error', 'details': str(error)}), 500


@app.after_request
def after_request_logging(response):
    """Log all responses including 404s"""
    if response.status_code >= 400:
        logger.warning(f"Response {response.status_code}: {request.method} {request.path}")
    return response


@app.before_request
def before_request_logging():
    logger.debug(f"Request: {request.method} {request.path} from {request.remote_addr}")


# ===== ROUTES =====



@app.route('/')
def landing():
    try:
        logger.info("Landing page requested")
        logger.info(f"Template folder: {app.template_folder}")
        logger.info(f"Template folder exists: {os.path.exists(app.template_folder)}")
        
        # List available templates
        if os.path.exists(app.template_folder):
            templates = os.listdir(app.template_folder)
            logger.info(f"Available templates: {templates}")
        
        result = render_template('index.html', username=session.get('username'))
        logger.info("Landing page rendered successfully")
        return result
    except Exception as e:
        logger.error(f"❌ Error rendering landing page: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(traceback.format_exc())
        return {
            'error': 'Failed to render landing page',
            'details': str(e),
            'error_type': type(e).__name__,
            'template_folder': app.template_folder,
            'template_folder_exists': os.path.exists(app.template_folder)
        }, 500


@app.route('/sports')
def sports():
    try:
        logger.info("Sports page requested")
        return render_template('sports.html', username=session.get('username'))
    except Exception as e:
        logger.error(f"Error rendering sports page: {e}")
        logger.error(traceback.format_exc())
        return {'error': 'Failed to render sports page', 'details': str(e)}, 500


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
            # Parsa foto con funzione ottimizzata
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
                'base_price': shirt['prezzo_base'],
                'current_price': shirt['offerta_attuale'],
                'end_time': formatta_data(shirt['data_fine']),
                'current_winner': shirt['vincitore_attuale'],
                'has_auction': shirt['id'] is not None,
                'auction_ended': auction_ended,
                'image': foto_list[0]  # Prima foto per la preview
            })
            
        
    except Exception as e:
        print(f"Error fetching shirts: {e}")
        
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
            'base_price': shirt_row['prezzo_base'],
            'current_price': shirt_row['offerta_attuale'],
            'end_time': formatta_data(shirt_row['data_fine']),
            'current_winner': shirt_row['vincitore_attuale'],
            'has_auction': shirt_row['id'] is not None,
            'sport': shirt_row['sport'],
            'images': parse_foto_urls(shirt_row['foto'], shirt_row['titolo']),
            'auction_ended': shirt_row['id'] is not None and shirt_row['stato'] == 'conclusa'
        }
        
    except Exception as e:
        print(f"Error fetching shirt details: {e}")
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
            WHERE id = %s 
                AND stato = 'in_corso' 
                AND (%s >= COALESCE(offerta_attuale, 0) + 1)
            RETURNING offerta_attuale, data_fine
        ''', (offerta, session.get('username'), asta_id, offerta))
        
        updated_auction = cur.fetchone()
        
        if not updated_auction:
            # Recupera il valore attuale e lo stato per il messaggio d'errore
            cur.execute('SELECT COALESCE(offerta_attuale, 0) as offerta_attuale, stato FROM asta WHERE id = %s', (asta_id,))
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
                VALUES (%s, NOW() AT TIME ZONE 'Europe/Rome', (NOW() AT TIME ZONE 'Europe/Rome') + INTERVAL '2 hours', %s, 'in_corso', %s)
                RETURNING id
            ''', (maglia_id, maglia['prezzo_base'], session.get('username')))
            
            result = cur.fetchone()
            conn.commit()
            flash(f'Asta avviata per "{maglia["titolo"]}" - Scade tra 2 ore', 'success')
            
        except Exception as e:
            if conn:
                conn.rollback()
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
        flash('❌ Devi accedere per visualizzare il tuo account', 'error')
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
                'final_price': auction['offerta_attuale'],
                'end_time': formatta_data(auction['data_fine']),
                'sport': auction['sport'],
                'image': foto_list[0]  # Prima foto
            })
        
    except Exception as e:
        print(f"Error fetching won auctions: {e}")
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
            print(f"Error during signup: {e}")
            flash('Errore durante la registrazione. Riprova più tardi.', 'error')
            return render_template('signup.html', username=session.get('username'))
        
        finally:
            release_connection(conn, cur)
    
    return render_template('signup.html', username=session.get('username'))



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


@app.route('/test')
def test():
    """Simple test endpoint"""
    return {
        'status': 'ok',
        'message': 'Test endpoint working',
        'timestamp': datetime.now().isoformat(),
        'render_deployment_id': os.getenv("RENDER_DEPLOYMENT_ID")
    }, 200


@app.route('/test/template')
def test_template():
    """Test if template rendering works"""
    try:
        logger.info("Test template endpoint called")
        from jinja2 import TemplateNotFound
        
        # Try to list available templates
        template_names = []
        try:
            import os
            templates_dir = os.path.join(app.root_path, 'templates')
            if os.path.exists(templates_dir):
                template_names = os.listdir(templates_dir)
        except Exception as e:
            logger.error(f"Error listing templates: {e}")
        
        return {
            'status': 'ok',
            'message': 'Template test endpoint working',
            'template_dir': app.jinja_loader.searchpath if hasattr(app.jinja_loader, 'searchpath') else 'unknown',
            'available_templates': template_names,
            'timestamp': datetime.now().isoformat()
        }, 200
    except Exception as e:
        logger.error(f"Error in test_template: {e}")
        logger.error(traceback.format_exc())
        return {
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        }, 500


@app.route('/health')
def health():
    logger.info("Health check requested")
    db_status = "unknown"
    try:
        # Verifica connessione al database
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        release_connection(conn, cur)
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"error: {str(e)}"
    
    return {
        'status': 'ok',
        'database': db_status,
        'environment': 'production' if is_production else 'development',
        'timestamp': datetime.now().isoformat()
    }, 200 if db_status == "connected" else 503


@app.route('/coffee')
def coffee():
    """Pagina per supportare il progetto con PayPal"""
    return render_template('coffee.html', username=session.get('username'))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=not is_production)
