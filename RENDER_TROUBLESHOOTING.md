# 🚨 Render Deployment - Troubleshooting Guide

## Problem: "Not Found" Error on Render

Se vedi una schermata nera con "Not Found" su Render, segui questi passaggi:

### 1. **Controlla i Logs di Render**
   - Vai al tuo progetto su [Render Dashboard](https://dashboard.render.com/)
   - Clicca sul tuo servizio (web service)
   - Vai a "Logs" per vedere gli errori di avvio
   - Cerca messaggi di errore come:
     - `DatabaseError` → Problema di connessione al database
     - `DATABASE_URL` → Variabile d'ambiente non impostata
     - `ImportError` → Problema con le dipendenze

### 2. **Verifica le Variabili d'Ambiente su Render**
   - Nel tuo servizio Render, vai a "Environment"
   - Assicurati che siano impostate TUTTE queste variabili:
     ```
     DATABASE_URL=postgresql://...
     SECRET_KEY=...
     SUPABASE_URL=...
     SERVICE_ROLE_KEY=...
     SUPABASE_BUCKET=...
     MAIL_USERNAME=...
     MAIL_PASSWORD=...
     MAIL_SERVER=...
     MAIL_PORT=...
     MAIL_USE_TLS=...
     ```
   - **⚠️ Non copiare da `.env`** - Render non supporta file `.env` nel deploy!
   - Copia/incolla manualmente ogni variabile

### 3. **Controlla se il Database è Raggiungibile**
   - Esegui questo comando locale:
     ```bash
     psql $DATABASE_URL -c "SELECT version();"
     ```
   - Se non funziona, il database potrebbe essere irraggiungibile da Render

### 4. **Verifica il Procfile**
   - Il file `Procfile` deve contenere:
     ```
     web: gunicorn --timeout 300 --workers 2 --max-requests 1000 main:app
     ```
   - Se non esiste, crealo

### 5. **Prova l'Health Check**
   Dopo il deploy, prova:
   ```
   GET https://your-render-url.onrender.com/health
   ```
   Dovrebbe ritornare:
   ```json
   {
     "status": "ok",
     "database": "connected",
     "environment": "production",
     "timestamp": "..."
   }
   ```

### 6. **Se il Pool di Connessioni Fallisce**
   I nuovi logs mostreranno chiaramente:
   ```
   ❌ DATABASE_URL environment variable not set!
   ```
   oppure:
   ```
   ❌ Database connection failed (OperationalError): ...
   ```

## Quick Checklist ✅
- [ ] Tutti le variabili d'ambiente sono impostate su Render?
- [ ] Il database è raggiungibile?
- [ ] Il Procfile esiste e è corretto?
- [ ] Hai fatto il push del codice a GitHub?
- [ ] Render ha completato il build/deploy?

## Debug Routes (Development Only)
Se vuoi testare localmente:
```bash
# Health check con stato del database
curl http://localhost:8080/health

# Info app (solo in development)
curl http://localhost:8080/debug
```

## Se Niente Funziona

1. **Riavvia il servizio su Render:**
   - Render Dashboard → Servizio → "Reboot Instance"

2. **Riconnetti il Git:**
   - Disconnetti il repository
   - Riconnettilo
   - Esegui un nuovo deploy

3. **Controlla i Requisiti:**
   - Verifica che `requirements.txt` abbia tutte le dipendenze:
     ```
     Flask==3.0.0
     Flask-Session
     gunicorn
     psycopg2-binary
     python-dotenv==1.0.0
     Flask-SQLAlchemy==3.1.1
     Pillow==11.0.0
     Flask-Mail==0.9.1
     supabase
     ```

---

**Ultima modifica:** May 26, 2026
