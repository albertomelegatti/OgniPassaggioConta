import os
import time
import io
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from supabase import create_client, Client
from PIL import Image

load_dotenv()

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Inizializza client Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_service_key = os.getenv("SERVICE_ROLE_KEY")
supabase_bucket = os.getenv("SUPABASE_BUCKET")

supabase: Client = create_client(supabase_url, supabase_service_key) if supabase_url and supabase_service_key else None




@admin_bp.route('/')
def dashboard():
    
    if not check_admin_permission():
        flash('Accesso negato. Solo gli admin possono accedere.', 'error')
        return redirect(url_for('landing'))
    
    total_shirts = 0
    active_auctions = 0
    total_users = 0
    total_bids = 0
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Ottieni il numero totale di maglie
        cur.execute('SELECT COUNT(*) AS count FROM maglia')
        total_shirts = cur.fetchone()['count']
        
        # Ottieni il numero di aste attive (con stato 'in_corso')
        cur.execute("SELECT COUNT(*) AS count FROM asta WHERE stato = 'in_corso'")
        active_auctions = cur.fetchone()['count']
        
        # Ottieni il numero totale di utenti
        cur.execute('SELECT COUNT(*) AS count FROM utente')
        total_users = cur.fetchone()['count']
    
    except Exception as e:
        print(f"Error in admin dashboard: {e}")
        flash(f'Errore: {str(e)}', 'error')
        
    finally:
        release_connection(conn, cur)
    
    return render_template('admin.html', total_shirts=total_shirts, active_auctions=active_auctions, total_users=total_users, total_bids=total_bids)



@admin_bp.route('/maglie', methods=['GET', 'POST'])
def maglie():
    
    if not check_admin_permission():
        flash('Accesso negato. Solo gli admin possono accedere.', 'error')
        return redirect(url_for('landing'))
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if request.method == 'POST':
            # Aggiungi nuova maglia
            titolo = request.form.get('titolo', '').strip()
            descrizione = request.form.get('descrizione', '').strip()
            prezzo_base = request.form.get('prezzo_base', '')
            sport = request.form.get('sport', '').strip()
            
            errors = []
            
            if not titolo or len(titolo) < 2:
                errors.append("Il titolo deve essere lungo almeno 2 caratteri")
            if not descrizione:
                errors.append("La descrizione è obbligatoria")
            if not prezzo_base or float(prezzo_base) <= 0:
                errors.append("Il prezzo base deve essere un numero positivo")
            if not sport or sport.lower() not in ['calcio', 'pallavolo', 'basket', 'ciclismo', 'sci']:
                errors.append("Lo sport selezionato non è valido")
            
            if errors:
                flash(' | '.join(errors), 'error')
                # Ricarica le maglie
                cur.execute('SELECT * FROM maglia ORDER BY sport, titolo')
                maglie_raw = cur.fetchall()
                
                # Parsifica il campo foto
                maglie = []
                for maglia in maglie_raw:
                    maglia_dict = dict(maglia)
                    if maglia_dict.get('foto'):
                        try:
                            # Prova prima come array JSON
                            maglia_dict['foto'] = json.loads(maglia_dict['foto']) if isinstance(maglia_dict['foto'], str) else maglia_dict['foto']
                            # Rimuovi le virgolette doppie dai link (se presenti)
                            maglia_dict['foto'] = [url.strip().strip('"') for url in maglia_dict['foto']]
                        except (json.JSONDecodeError, TypeError):
                            # Se non è JSON valido, prova come stringa separata da virgole
                            try:
                                maglia_dict['foto'] = [f.strip().strip('"') for f in maglia_dict['foto'].split(',') if f.strip()]
                            except:
                                maglia_dict['foto'] = []
                    else:
                        maglia_dict['foto'] = []
                    maglie.append(maglia_dict)
                
                return render_template('admin_maglie.html', maglie=maglie)
            
            # Gestisci upload foto (fino a 2)
            foto_paths = []
            files = request.files.getlist('foto')
            
            for file in files[:2]:  # Max 2 foto
                if file and file.filename and allowed_file(file.filename):
                    if supabase:
                        # Upload su Supabase Storage
                        public_url = upload_to_supabase(file)
                        if public_url:
                            foto_paths.append(public_url)
                    else:
                        # Fallback: salvataggio locale (per sviluppo senza Supabase)
                        filename = secure_filename(f"{int(time.time())}_{file.filename}")
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        file.save(filepath)
                        foto_paths.append(f"uploads/{filename}")
            
            # Inserisci la maglia nel database
            foto_json = json.dumps(foto_paths) if foto_paths else None
            
            try:
                cur.execute('''
                    INSERT INTO maglia (titolo, descrizione, prezzo_base, sport, foto)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                ''', (titolo, descrizione, float(prezzo_base), sport.lower(), foto_json))
                
                conn.commit()
                flash(f'Maglia "{titolo}" aggiunta con successo!', 'success')
                return redirect(url_for('admin.maglie'))
            except Exception as e:
                if conn:
                    conn.rollback()
                print(f"Error inserting maglia: {e}")
                flash(f'Errore nell\'aggiunta della maglia: {str(e)}', 'error')
                return redirect(url_for('admin.maglie'))
        
        # GET: mostra tutte le maglie
        cur.execute('SELECT * FROM maglia ORDER BY sport, titolo')
        maglie_raw = cur.fetchall()
        
        # Parsifica il campo foto (da JSON string a list, o da virgole)
        maglie = []
        for maglia in maglie_raw:
            maglia_dict = dict(maglia)
            if maglia_dict.get('foto'):
                try:
                    # Prova prima come array JSON
                    maglia_dict['foto'] = json.loads(maglia_dict['foto']) if isinstance(maglia_dict['foto'], str) else maglia_dict['foto']
                    # Rimuovi le virgolette doppie dai link (se presenti)
                    maglia_dict['foto'] = [url.strip().strip('"') for url in maglia_dict['foto']]
                except (json.JSONDecodeError, TypeError):
                    # Se non è JSON valido, prova come stringa separata da virgole
                    try:
                        maglia_dict['foto'] = [f.strip().strip('"') for f in maglia_dict['foto'].split(',') if f.strip()]
                    except:
                        maglia_dict['foto'] = []
            else:
                maglia_dict['foto'] = []
            maglie.append(maglia_dict)
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error in admin maglie: {e}")
        flash(f'Errore: {str(e)}', 'error')
        maglie = []
    
    finally:
        release_connection(conn, cur)
    
    return render_template('admin_maglie.html', maglie=maglie)




@admin_bp.route('/maglie/<int:maglia_id>', methods=['DELETE'])
def delete_maglia(maglia_id):
    
    if not check_admin_permission():
        return jsonify({'error': 'Accesso negato'}), 403
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Ottieni le foto da eliminare con lock pessimistico per evitare race condition
        cur.execute('SELECT foto FROM maglia WHERE id = %s FOR UPDATE', (maglia_id,))
        maglia = cur.fetchone()
        
        if not maglia:
            return jsonify({'error': 'Maglia non trovata'}), 404
        
        # Elimina i file foto
        if maglia['foto']:
            try:
                # Prova prima come array JSON
                foto_paths = json.loads(maglia['foto']) if isinstance(maglia['foto'], str) else maglia['foto']
                # Rimuovi le virgolette doppie dai link (se presenti)
                foto_paths = [url.strip().strip('"') for url in foto_paths]
            except (json.JSONDecodeError, TypeError):
                # Se non è JSON valido, prova come stringa separata da virgole
                try:
                    foto_paths = [f.strip().strip('"') for f in maglia['foto'].split(',') if f.strip()]
                except:
                    foto_paths = []
            
            for foto_path in foto_paths:
                try:
                    if foto_path.startswith('http'):
                        if supabase:
                            # Estrai il path dal URL
                            file_path = foto_path.split(f"/{supabase_bucket}/")[-1]
                            supabase.storage.from_(supabase_bucket).remove([file_path])
                    else:
                        # È un path locale
                        filepath = os.path.join('static', foto_path)
                        if os.path.exists(filepath):
                            os.remove(filepath)
                except Exception as e:
                    print(f"Error deleting file {foto_path}: {e}")
        
        # Elimina tutte le aste associate a questa maglia (vincolo foreign key)
        cur.execute('DELETE FROM asta WHERE id_maglia = %s', (maglia_id,))
        
        # Elimina la maglia dal database
        cur.execute('DELETE FROM maglia WHERE id = %s', (maglia_id,))
        conn.commit()
        
        return jsonify({'success': True}), 200
    
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error deleting maglia: {e}")
        return jsonify({'error': str(e)}), 500
    
    finally:
        release_connection(conn, cur)


@admin_bp.route('/users', methods=['GET', 'POST'])
def users():
    # Verifica che l'utente corrente sia un superAdmin
    if not session.get('logged_in') or session.get('permessi') != 'superAdmin':
        flash('Accesso negato. Solo i superAdmin possono accedere.', 'error')
        return redirect(url_for('landing'))
    
    conn = None
    cur = None
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if request.method == 'POST':
            # Gestisci le richieste di cambio permessi
            action = request.form.get('action')  # 'grant' o 'revoke'
            username = request.form.get('username', '').strip()
            
            if not action or not username:
                flash('Dati non validi.', 'error')
                return redirect(url_for('admin.users'))
            
            # Previeni che un superAdmin modifichi se stesso
            if username == session.get('username'):
                flash('Non puoi modificare i tuoi stessi permessi.', 'error')
                return redirect(url_for('admin.users'))
            
            # Verifica che l'utente esista
            cur.execute('SELECT permessi FROM utente WHERE username = %s', (username,))
            user = cur.fetchone()
            
            if not user:
                flash(f'Utente "{username}" non trovato.', 'error')
                return redirect(url_for('admin.users'))
            
            try:
                if action == 'grant':
                    # Concedi il permesso admin
                    if user['permessi'] in ['admin', 'superAdmin']:
                        flash(f'Utente "{username}" ha già permessi admin.', 'error')
                    else:
                        cur.execute(
                            'UPDATE utente SET permessi = %s WHERE username = %s',
                            ('admin', username)
                        )
                        conn.commit()
                        flash(f'Permesso admin concesso a "{username}".', 'success')
                
                elif action == 'revoke':
                    # Revoca il permesso admin
                    if user['permessi'] == 'superAdmin':
                        flash('Non puoi revocare i permessi ad un altro superAdmin.', 'error')
                    elif user['permessi'] == 'base':
                        flash(f'Utente "{username}" non ha permessi admin.', 'error')
                    else:
                        cur.execute(
                            'UPDATE utente SET permessi = %s WHERE username = %s',
                            ('base', username)
                        )
                        conn.commit()
                        flash(f'Permesso admin revocato da "{username}".', 'success')
                else:
                    flash('Azione non valida.', 'error')
            
            except Exception as e:
                if conn:
                    conn.rollback()
                print(f"Error updating user permission: {e}")
                flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
            
            return redirect(url_for('admin.users'))
        
        # GET: mostra tutti gli utenti
        cur.execute('''
            SELECT username, email, permessi
            FROM utente
            ORDER BY 
                CASE 
                    WHEN permessi = 'superAdmin' THEN 1
                    WHEN permessi = 'admin' THEN 2
                    ELSE 3
                END,
                username
        ''')
        
        utenti = cur.fetchall()
        utenti_list = [dict(utente) for utente in utenti]
        
        return render_template('admin_users.html', utenti=utenti_list)
    
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error in admin users: {e}")
        flash(f'Errore: {str(e)}', 'error')
        utenti_list = []
        return render_template('admin_users.html', utenti=utenti_list)
    
    finally:
        release_connection(conn, cur)





def allowed_file(filename):
    # Verifica se il file ha un'estensione consentita.
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def compress_image(file, max_size_mb=0.5):
    # Comprime un'immagine riducendo qualità o ridimensionando.
    try:
        file.seek(0)  # Reset pointer
        img = Image.open(file)
        
        # Converti RGBA in RGB (alcuni formati non supportati)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        # Salva in memoria con qualità ridotta
        output = io.BytesIO()
        quality = 75
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # Riduci la qualità fino a stare sotto il limite
        while quality > 10:
            output.seek(0)
            output.truncate(0)
            img.save(output, format='JPEG', quality=quality, optimize=True)
            size = len(output.getvalue())
            
            if size <= max_size_bytes:
                output.seek(0)
                return output
            
            quality -= 5
        
        # Se anche con qualità 10 è ancora grande, ridimensiona
        img.thumbnail((1200, 800), Image.Resampling.LANCZOS)
        output.seek(0)
        output.truncate(0)
        img.save(output, format='JPEG', quality=10, optimize=True)
        output.seek(0)
        return output
        
    except Exception as e:
        print(f"❌ Errore compressione: {e}")
        return None


def upload_to_supabase(file, folder="maglie"):
    # Carica un'immagine su Supabase Storage dopo compressione.
    if not supabase or not file:
        return None
    
    try:
        # Comprimi l'immagine (max 2MB)
        compressed_file = compress_image(file, max_size_mb=2)
        if not compressed_file:
            return None
        
        # Genera nome file univoco
        filename = secure_filename(f"{int(time.time() * 1000)}_{file.filename}")
        file_path = f"{folder}/{filename}"
        
        # Carica su Supabase Storage
        response = supabase.storage.from_(supabase_bucket).upload(
            path=file_path,
            file=compressed_file.getvalue(),
            file_options={"content-type": "image/jpeg"}
        )
        
        # Genera l'URL pubblico
        public_url = supabase.storage.from_(supabase_bucket).get_public_url(file_path)
        
        return public_url
    
    except Exception as e:
        return None


def check_admin_permission():
    # Verifica se l'utente corrente è un admin.
    if not session.get('logged_in') or session.get('permessi') not in ['admin', 'superAdmin']:
        return False
    return True
