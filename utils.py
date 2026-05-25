import json
from flask import Blueprint, request, current_app
from flask_mail import Mail, Message
from db import get_connection, release_connection
from psycopg2.extras import RealDictCursor
import os

mail = None


def parse_foto_urls(foto_raw, titolo_maglia=""):
    """Parsa i link foto da formato JSON o CSV. Fallback a placeholder.
    
    Args:
        foto_raw: Stringa JSON array o CSV di URL
        titolo_maglia: Titolo per generare placeholder
    
    Returns:
        Lista di URL puliti, almeno uno (placeholder se vuoto)
    """
    if not foto_raw:
        return [get_placeholder_image(titolo_maglia)]
    
    foto_list = []
    
    try:
        # Prova JSON
        foto_list = json.loads(foto_raw) if isinstance(foto_raw, str) else foto_raw
    except (json.JSONDecodeError, TypeError):
        # Fallback: prova CSV
        try:
            foto_list = [f.strip() for f in foto_raw.split(',') if f.strip()]
        except:
            foto_list = []
    
    # Pulisci ogni URL una sola volta (strip + quote removal)
    foto_list = [url.strip().strip('"') for url in foto_list if url]
    
    # Se vuoto, usa placeholder
    return foto_list or [get_placeholder_image(titolo_maglia)]


def get_placeholder_image(titolo_maglia):
    # Genera URL placeholder per immagine manca.
    return f'https://via.placeholder.com/300x400?text={titolo_maglia.replace(" ", "+")}'


# EMAIL BLUEPRINT

email_bp = Blueprint('email', __name__)

def init_email(app):
    """Configura Flask-Mail con l'app"""
    global mail
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')
    mail = Mail(app)

@email_bp.route("/email/status")
def email_status():
    return "Server attivo"






@email_bp.route("/auction-ended", methods=['POST'])
def auction_ended():
    
    conn = None
    cur = None
    
    try:
        payload = request.get_json()
        
        if not payload or 'record' not in payload:
            return "Payload non valido", 400
        
        auction_id = payload['record'].get('id')
        if not auction_id:
            return "ID asta mancante nel payload", 400
        
        old_state = payload.get('old_record', {}).get('stato')
        new_state = payload['record'].get('stato')
        
        if old_state != 'in_corso' or new_state != 'conclusa':
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
                        JOIN utente u ON a.vincitore_attuale = u.username
                        WHERE a.id = %s;
                    ''', (auction_id,))
        auction_info = cur.fetchone()
        
        if not auction_info:
            return "Asta non trovata", 404
        
        foto_urls = parse_foto_urls(auction_info['foto'], auction_info['titolo'])
        
        logo_url = f"{request.host_url.rstrip('/')}/static/images/logo/logo.jpg"
        
        # Prendi la prima foto per mostrare nella email
        prima_foto = foto_urls[0] if foto_urls else None
        
        # Composizione del body come HTML
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto;">
                    <img src="{logo_url}" alt="Logo" style="max-width: 200px; margin-bottom: 20px;">
                    
                    <hr style="border: none; border-top: 2px solid #ddd; margin: 20px 0;">
                    
                    <h2 style="color: #2c3e50; text-align: center;">OGNI PASSAGGIO CONTA - Asta Sportiva</h2>
                    
                    <hr style="border: none; border-top: 2px solid #ddd; margin: 20px 0;">
                    
                    <h3 style="color: #27ae60;">Congratulazioni!</h3>
                    
                    <p>L'asta per la maglia <strong>"{auction_info['titolo']}"</strong> è terminata e <strong>hai vinto!</strong></p>
                    
                    <h4 style="color: #2c3e50;">Dettagli dell'asta:</h4>
                    <ul style="background-color: #f5f5f5; padding: 15px; border-radius: 5px;">
                        <li><strong>Articolo:</strong> {auction_info['titolo']}</li>
                        <li><strong>Descrizione:</strong> {auction_info['descrizione']}</li>
                        <li><strong>Offerta finale:</strong> €{auction_info['offerta_attuale']}</li>
                    </ul>
                    
                    {f'<div style="margin: 20px 0;"><img src="{prima_foto}" alt="{auction_info["titolo"]}" style="max-width: 300px; border-radius: 5px;"></div>' if prima_foto else ''}
                    
                    <p style="margin-top: 30px; color: #7f8c8d;">Per completare l'acquisto, accedi al tuo account e finalizza l'ordine.</p>
                    
                    <p style="margin-top: 30px; text-align: center; color: #7f8c8d;">
                        <strong>Grazie per aver partecipato!</strong><br>
                        Ogni Passaggio Conta
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg = Message(
            subject="Congratulazioni! Hai vinto l'asta",
            sender=current_app.config['MAIL_USERNAME'],
            recipients=[auction_info['email']],
            html=html_body
        )
        
        mail.send(msg)
        
        return "Email di notifica inviata correttamente!"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
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
