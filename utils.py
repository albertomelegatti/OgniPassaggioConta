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
    
    # Verifica che le variabili d'ambiente siano presenti
    mail_user = os.getenv('MAIL_USERNAME')
    mail_pass = os.getenv('MAIL_PASSWORD')
    
    if not mail_user or not mail_pass:
        print("❌ ERRORE: MAIL_USERNAME o MAIL_PASSWORD non configurati!")
        return
    
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = mail_user
    app.config['MAIL_PASSWORD'] = mail_pass
    app.config['MAIL_DEFAULT_SENDER'] = mail_user
    app.config['MAIL_DEBUG'] = True  # Abilita debug di Flask-Mail
    
    mail = Mail(app)
    print(f"✅ Email configurata correttamente per {mail_user}")

@email_bp.route("/email/status")
def email_status():
    return "Server attivo"







@email_bp.route("/auction-ended", methods=['POST'])
def auction_ended():
    """Webhook per notificare il vincitore quando l'asta termina"""
    
    print("\n" + "="*60)
    print("🔔 WEBHOOK /auction-ended ricevuto")
    print("="*60)
    
    # Verifica che mail sia stato inizializzato
    if mail is None:
        print("❌ ERRORE CRITICO: Email non inizializzata")
        print("   Assicurati che init_email(app) sia stato chiamato in main.py")
        return {"error": "Email non configurata", "status": 500}, 500
    
    print("✅ Mail object trovato")
    
    conn = None
    cur = None
    
    try:
        # Debug: stampa il payload ricevuto
        payload = request.get_json()
        print(f"\n📋 Payload ricevuto: {json.dumps(payload, indent=2, default=str)}")
        
        if not payload or 'record' not in payload:
            print("❌ Payload non valido - 'record' non trovato")
            return {"error": "Payload non valido"}, 400
        
        auction_id = payload['record'].get('id')
        if not auction_id:
            print("❌ ID asta mancante nel payload")
            return {"error": "ID asta mancante"}, 400
        
        print(f"\n🎯 Processando asta ID: {auction_id}")
        
        old_state = payload.get('old_record', {}).get('stato')
        new_state = payload['record'].get('stato')
        
        print(f"   Stato precedente: {old_state}")
        print(f"   Nuovo stato: {new_state}")
        
        if old_state != 'in_corso' or new_state != 'conclusa':
            print(f"⚠️ Transizione stato non valida - non è una conclusione")
            return {"message": "Transizione non richiesta (non è una conclusione)"}, 200
        
        print("✅ Transizione stato valida")
    except Exception as e:
        print(f"❌ Errore parsing payload: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"Errore parsing: {str(e)}"}, 400
    
    try:
        print("\n🔌 Connessione al database...")
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        print("✅ Connessione riuscita")
        
        print(f"\n🔍 Cercando asta {auction_id}...")
        cur.execute('''
                        SELECT a.offerta_attuale, a.vincitore_attuale, m.titolo, m.descrizione, m.foto, u.email
                        FROM asta a
                        JOIN maglia m ON a.id_maglia = m.id
                        JOIN utente u ON a.vincitore_attuale = u.username
                        WHERE a.id = %s;
                    ''', (auction_id,))
        auction_info = cur.fetchone()
        
        if not auction_info:
            print(f"❌ Asta {auction_id} non trovata nel database")
            return {"error": "Asta non trovata"}, 404
        
        print("✅ Asta trovata")
        print(f"   Titolo: {auction_info['titolo']}")
        print(f"   Vincitore: {auction_info['vincitore_attuale']}")
        print(f"   Email: {auction_info['email']}")
        
        # Verifica che il vincitore abbia un'email
        winner_email = auction_info.get('email')
        if not winner_email:
            print(f"❌ Email del vincitore non disponibile")
            return {"error": "Email vincitore non disponibile"}, 400
        
        print("\n📸 Parsing foto...")
        foto_urls = parse_foto_urls(auction_info['foto'], auction_info['titolo'])
        print(f"✅ {len(foto_urls)} foto trovate")
        
        logo_url = f"{request.host_url.rstrip('/')}/static/images/logo/logo.jpg"
        prima_foto = foto_urls[0] if foto_urls else None
        
        print("\n📧 Costruendo email...")
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
                    
                    <p style="margin-top: 30px; text-align: center; color: #7f8c8d;">
                        <strong>Grazie per aver partecipato!</strong><br>
                        Ogni Passaggio Conta
                    </p>
                </div>
            </body>
        </html>
        """
        print("✅ Email costruita")
        
        print(f"\n📤 Inviando email a {winner_email}...")
        msg = Message(
            subject="Congratulazioni! Hai vinto l'asta",
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            recipients=[winner_email],
            html=html_body
        )
        
        mail.send(msg)
        print(f"✅ EMAIL INVIATA CON SUCCESSO a {winner_email}")
        print("="*60 + "\n")
        
        return {"success": True, "message": "Email inviata correttamente"}, 200
        
    except Exception as e:
        import traceback
        print(f"\n❌ ERRORE INVIO EMAIL: {str(e)}")
        print("Traceback completo:")
        traceback.print_exc()
        print("="*60 + "\n")
        return {"error": f"Errore invio email: {str(e)}"}, 500
    
    finally:
        release_connection(conn, cur)


@email_bp.route("/send-test")
def send_test_email():
    """Endpoint di test per verificare che l'email funziona"""
    
    print("\n" + "="*60)
    print("📧 TEST EMAIL AVVIATO")
    print("="*60)
    
    if mail is None:
        print("❌ ERRORE CRITICO: Email non inizializzata!")
        return {"error": "Email non configurata"}, 500
    
    print("✅ Mail object trovato")
    
    try:
        test_recipient = os.getenv('MAIL_USERNAME')
        if not test_recipient:
            print("❌ Email di destinazione non configurata")
            return {"error": "Email destinazione non trovata"}, 400
        
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        print(f"📤 Parametri email:")
        print(f"   From: {sender}")
        print(f"   To: {test_recipient}")
        
        msg = Message(
            subject="✅ Email di test - Ogni Passaggio Conta",
            sender=sender,
            recipients=[test_recipient],
            body="Funziona! Email inviata da Flask su Render."
        )

        print("📮 Inviando email...")
        mail.send(msg)
        print(f"✅ EMAIL DI TEST INVIATA CON SUCCESSO a {test_recipient}")
        print("="*60 + "\n")
        return {"success": True, "message": f"Email di test inviata a {test_recipient}"}, 200

    except Exception as e:
        import traceback
        print(f"❌ ERRORE INVIO EMAIL DI TEST: {str(e)}")
        print("Traceback completo:")
        traceback.print_exc()
        print("="*60 + "\n")
        return {"error": f"Errore invio email: {str(e)}"}, 500
