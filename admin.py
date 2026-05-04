import os
import time
import io
import json
from datetime import datetime, timedelta
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
    return render_template('admin.html')



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
                errors.append("Titolo deve essere almeno 2 caratteri")
            if not descrizione:
                errors.append("Descrizione è obbligatoria")
            if not prezzo_base or float(prezzo_base) <= 0:
                errors.append("Prezzo base deve essere un numero positivo")
            if not sport or sport.lower() not in ['calcio', 'pallavolo', 'basket', 'ciclismo', 'sci']:
                errors.append("Sport selezionato non valido")
            
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
            
            cur.execute('''
                INSERT INTO maglia (titolo, descrizione, prezzo_base, sport, foto)
                VALUES (%s, %s, %s, %s, %s)
            ''', (titolo, descrizione, float(prezzo_base), sport.lower(), foto_json))
            
            conn.commit()
            flash(f'Maglia "{titolo}" aggiunta con successo!', 'success')
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
            conn.rollback()
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
        
        # Ottieni le foto da eliminare
        cur.execute('SELECT foto FROM maglia WHERE id = %s', (maglia_id,))
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
            conn.rollback()
        print(f"Error deleting maglia: {e}")
        return jsonify({'error': str(e)}), 500
    
    finally:
        release_connection(conn, cur)





def allowed_file(filename):
    # Verifica se il file ha un'estensione consentita.
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def compress_image(file, max_size_mb=2):
    # Comprime un'immagine riducendo qualità o ridimensionando.
    try:
        file.seek(0)  # Reset pointer
        img = Image.open(file)
        
        # Converti RGBA in RGB (alcuni formati non supportati)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        # Salva in memoria con qualità ridotta
        output = io.BytesIO()
        quality = 85
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # Riduci la qualità fino a stare sotto il limite
        while quality > 10:
            output.seek(0)
            output.truncate(0)
            img.save(output, format='JPEG', quality=quality, optimize=True)
            size = len(output.getvalue())
            
            if size <= max_size_bytes:
                print(f"✅ Immagine compressa: qualità {quality}, size {size/1024/1024:.2f}MB")
                output.seek(0)
                return output
            
            quality -= 5
        
        # Se anche con qualità 10 è ancora grande, ridimensiona
        img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
        output.seek(0)
        output.truncate(0)
        img.save(output, format='JPEG', quality=10, optimize=True)
        print(f"✅ Immagine ridimensionata: size {len(output.getvalue())/1024/1024:.2f}MB")
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
            print(f"❌ Impossibile comprimere l'immagine")
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
        print(f"✅ Immagine caricata su Supabase: {file_path}")
        
        return public_url
    
    except Exception as e:
        print(f"❌ Error uploading to Supabase: {e}")
        return None


def check_admin_permission():
    # Verifica se l'utente corrente è un admin.
    if not session.get('user_id') or session.get('permessi') != 'admin':
        return False
    return True
