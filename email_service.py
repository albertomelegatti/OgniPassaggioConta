from flask import Blueprint, request
from flask_mail import Mail, Message
from db import get_connection, release_connection
from psycopg2.extras import RealDictCursor
from utils import parse_foto_urls
import os
import textwrap

mail = Mail()

email_bp = Blueprint('email', __name__)

def init_email(app):
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    mail.init_app(app)

@email_bp.route("/")
def home():
    return "Server attivo"




@email_bp.route("/auction-ended/<auction_id>", methods=['POST'])
def auction_ended(auction_id):
    
    print(f"Ricevuta richiesta di notifica per asta ID: {auction_id}")
    
    conn = None
    cur = None
    
    if not auction_id:
        return "ID dell'asta mancante", 400
    
    # Verifica che l'update riguardasse lo stato dell'asta
    try:
        payload = request.get_json()
        if not payload or 'record' not in payload:
            return "Payload non valido", 400
        
        # Controlla che lo stato passi da 'in_corso' a 'conclusa'
        old_state = payload.get('old', {}).get('stato')
        new_state = payload['record'].get('stato')
        
        if old_state != 'in_corso' or new_state != 'conclusa':
            print(f"Asta {auction_id}: transizione stato non valida ({old_state} -> {new_state}), ignoro")
            return "Transizione stato non valida", 200
    except Exception as e:
        return f"Errore parsing payload: {str(e)}", 400
    
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
                        SELECT a.offerta_attuale, a.vincitore_attuale, m.titolo, m.descrizione, m.foto, u.email
                        FROM asta a
                        JOIN maglia m ON a.id_maglia = m.id
                        JOIN utente u ON a.vincitore_attuale = u.id
                        WHERE a.id = %s;
                    ''', (auction_id,))
        auction_info = cur.fetchone()
        
        if not auction_info:
            return "Asta non trovata", 404
        
        # Parsing delle foto usando la funzione dedicata
        foto_urls = parse_foto_urls(auction_info['foto'], auction_info['titolo'])
        
        # URL del logo dalla repo
        logo_url = f"{request.host_url.rstrip('/')}/static/images/logo/logo.jpg"
        
        # Composizione del body dell'email
        foto_section = ""
        if foto_urls:
            foto_section = "\nFoto della maglia:\n" + "\n".join(foto_urls)
        
        body = textwrap.dedent(f"""
            [LOGO: {logo_url}]
            
            ═══════════════════════════════════════════════════════════
            OGNI PASSAGGIO CONTA - Asta Sportiva
            ═══════════════════════════════════════════════════════════
            
            Congratulazioni!

            L'asta per la maglia "{auction_info['titolo']}" è terminata e hai vinto!

            Dettagli dell'asta:
            - Articolo: {auction_info['titolo']}
            - Descrizione: {auction_info['descrizione']}
            - Offerta finale: €{auction_info['offerta_attuale']}{foto_section}

            Per completare l'acquisto, accedi al tuo account e finalizza l'ordine.

            Grazie per aver partecipato!
            
            ═══════════════════════════════════════════════════════════
            Ogni Passaggio Conta
        """).strip()
        
        msg = Message(
            subject="Congratulazioni! Hai vinto l'asta",
            sender=os.getenv('MAIL_USERNAME'),
            recipients=[auction_info['email']],
            body=body
        )
        mail.send(msg)
        return "Email di notifica inviata correttamente!"
        
    except Exception as e:
        return f"Errore invio email: {str(e)}"
    
    finally:
        if cur:
            cur.close()
        if conn:
            release_connection(conn)
    



@email_bp.route("/send-test")
def send_test_email():
    try:
        msg = Message(
            subject="Email di test Flask",
            sender=os.getenv('MAIL_USERNAME'),
            recipients=["melegattialberto@gmail.com"],
            body="Funziona! Email inviata da Flask su Render."
        )

        mail.send(msg)

        return "Email inviata correttamente!"

    except Exception as e:
        return f"Errore invio email: {str(e)}"
