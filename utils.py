import json
from flask import Blueprint, request, current_app
from flask_mail import Mail, Message
from db import get_connection, release_connection
from psycopg2.extras import RealDictCursor
import os

mail = None


def add_image_compression(url, quality=60, max_width=800):
    """Aggiunge parametri di compressione agli URL Supabase.
    
    Args:
        url: URL dell'immagine
        quality: Qualità JPEG (1-100, default 60)
        max_width: Larghezza massima (default 800px)
    
    Returns:
        URL con parametri di compressione
    """
    if not url or "supabase" not in url:
        return url
    
    # Supabase Image Transformation parameters
    params = f"?width={max_width}&quality={quality}&resize=contain"
    
    # Se l'URL contiene già query params, usa &
    if "?" in url:
        return url + f"&width={max_width}&quality={quality}&resize=contain"
    
    return url + params


def parse_foto_urls(foto_raw, titolo_maglia="", compress=True):
    """Parsa i link foto da formato JSON o CSV. Fallback a placeholder.
    
    Args:
        foto_raw: Stringa JSON array o CSV di URL
        titolo_maglia: Titolo per generare placeholder
        compress: Se True, comprime le immagini da Supabase
    
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
    
    # Comprimi immagini Supabase per velocità
    if compress:
        foto_list = [add_image_compression(url) for url in foto_list]
    
    # Se vuoto, usa placeholder
    return foto_list or [get_placeholder_image(titolo_maglia)]


def get_placeholder_image(titolo_maglia):
    # Genera URL placeholder per immagine manca.
    return f'https://via.placeholder.com/300x400?text={titolo_maglia.replace(" ", "+")}'


def get_paypal_payment_link(amount):
    """Genera un link PayPal.me per pagare l'importo indicato.

    L'account di destinazione e' deciso dall'amministratore tramite la
    variabile d'ambiente PAYPAL_ME_USERNAME (lo username scelto su
    paypal.me/<username>). Se non e' impostata, ritorna None e il bottone
    di pagamento viene semplicemente omesso ovunque venga usato.
    """
    username = os.getenv("PAYPAL_ME_USERNAME")
    if not username or amount is None:
        return None
    return f"https://paypal.me/{username}/{float(amount):.2f}EUR"


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
    """Webhook per notificare il vincitore quando l'asta termina"""
    
    # Verifica che mail sia stato inizializzato
    if mail is None:
        return {"error": "Email non configurata", "status": 500}, 500
    
    conn = None
    cur = None
    
    try:
        payload = request.get_json()
        
        if not payload or 'record' not in payload:
            return {"error": "Payload non valido"}, 400
        
        auction_id = payload['record'].get('id')
        if not auction_id:
            return {"error": "ID asta mancante"}, 400
        
        old_state = payload.get('old_record', {}).get('stato')
        new_state = payload['record'].get('stato')
        
        if old_state != 'in_corso' or new_state != 'conclusa':
            return {"message": "Transizione non richiesta (non è una conclusione)"}, 200
    except Exception as e:
        return {"error": f"Errore parsing: {str(e)}"}, 400
    
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
            return {"error": "Asta non trovata"}, 404
        
        # Verifica che il vincitore abbia un'email
        winner_email = auction_info.get('email')
        if not winner_email:
            current_app.logger.warning("Email del vincitore non disponibile per auction_id=%s", auction_id)
            return {"error": "Email vincitore non disponibile"}, 400
        
        foto_urls = parse_foto_urls(auction_info['foto'], auction_info['titolo'])

        logo_url = f"{request.host_url.rstrip('/')}/static/images/logo/logo.jpg"
        prima_foto = foto_urls[0] if foto_urls else None
        paypal_link = get_paypal_payment_link(auction_info['offerta_attuale'])
        
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

                    {f'<div style="text-align: center; margin: 24px 0;"><a href="{paypal_link}" style="background-color: #0070ba; color: #ffffff; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block;">Paga con PayPal</a></div>' if paypal_link else ''}

                    {f'<div style="margin: 20px 0;"><img src="{prima_foto}" alt="{auction_info["titolo"]}" style="max-width: 300px; border-radius: 5px;"></div>' if prima_foto else ''}

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
            sender=("Ogni Passaggio Conta", current_app.config['MAIL_DEFAULT_SENDER']),
            recipients=[winner_email],
            html=html_body
        )
        
        mail.send(msg)
        current_app.logger.info("Email inviata con successo a %s per auction_id=%s", winner_email, auction_id)

        return {"success": True, "message": "Email inviata correttamente"}, 200

    except Exception as e:
        current_app.logger.exception("Errore invio email per auction_id=%s", auction_id)
        return {"error": f"Errore invio email: {str(e)}"}, 500
    
    finally:
        release_connection(conn, cur)
