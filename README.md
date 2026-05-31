# Ogni Passaggio Conta

Una piattaforma web creata per una giornata di beneficenza. Gestisce sign-up e login degli utenti e implementa un sistema di aste di maglie sportive. Interfaccia responsive con design moderno e gestione robusta dei dati attraverso PostgreSQL.

[https://ognipassaggioconta.onrender.com/](https://ognipassaggioconta.onrender.com/)

## Tech Stack

### Backend
- **Framework**: Flask 3.0.0 - microframework Python leggero e scalabile
- **Linguaggio**: Python 3.11+
- **Gestione Database**: SQLAlchemy ORM con psycopg2
- **Server**: Gunicorn web server (timeout 120s, 8 worker)
- **Sessioni**: Flask-Session con backend database persistente
- **Email**: Flask-Mail per invio comunicazioni

### Database
- **Sistema**: PostgreSQL (Supabase Hosted)
- **Connection Pooling**: ThreadedConnectionPool per gestione efficiente connessioni
- **Ricycling**: Pool ricyclato ogni 1 ora per connessioni stabili
- **Health Check**: Pre-ping abilitato per validare connessioni attive
- **Dimensione Pool**: 15 connessioni per gestire carico concorrente

### Frontend
- **Template Engine**: Jinja2 (integrato Flask)
- **Styling**: CSS custom
- **Interattività**: JavaScript vanilla
- **Gestione Immagini**: Pillow per elaborazione e upload file
- **Interfaccia Responsiva**: HTML5 semantico
- **Asset Statici**: WhiteNoise per servizio ottimizzato file statici

### Integrazioni Esterne
- **Supabase**: Hosting PostgreSQL managed
- **Sistema Email**: SMTP con Flask-Mail

### DevOps & Deployment
- **Server Application**: Gunicorn (120s timeout, 8 sync worker, 500 max request)
- **Procfile**: Supporto Heroku e Render deployment
- **Gestione Dipendenze**: pip + requirements.txt
- **Variabili d'Ambiente**: python-dotenv per configurazione

## Caratteristiche Principali

### Gestione Catalogo Prodotti
- Visualizzazione completa dei prodotti (maglie, scarpe, articoli sportivi, bevande)
- Dettagli prodotto con immagini e descrizioni
- Gestione categoria: maglie, scarpe, articoli sportivi, bevande
- Interfaccia dedicata per visualizzazione singolo articolo

### Sistema di Autenticazione
- Registrazione sicura con password hashate (werkzeug.security)
- Login con sessione persistente (30 giorni)
- Reset password tramite email
- Gestione profilo utente

### Area Amministrativa
- Dashboard amministratore con accesso privilegiato
- Gestione utenti: visualizzazione, modifica, eliminazione
- Gestione maglie (CRUD operazioni)
- Gestione articoli per categoria
- Sistema di controllo accesso basato su ruoli

### Upload Multimediale
- Upload immagini prodotti con validazione
- Gestione cartella uploads personalizzata
- Supporto formati immagine standard (JPG, PNG)
- Archiviazione file statica in directory dedicated
- Elaborazione immagini con Pillow

### Sistema Email
- Invio email per comunicazioni utente
- Notifiche registrazione e reset password
- Integrazione SMTP configurabile

### Gestione Sessioni
- Sessioni sicure con scadenza 30 giorni
- Cookie HTTPOnly e Secure
- SameSite policy Lax per CSRF protection
- Persistenza sessione in database

## Struttura del Progetto

```
├── main.py                    # Applicazione Flask principale
├── admin.py                   # Blueprint area amministrativa
├── db.py                      # Gestione connessioni database e pool
├── utils.py                   # Funzioni utilità e blueprint email
├── hash_password.py           # Utilità hashing password
├── test_config.py             # Configurazione test
├── Procfile                   # Configurazione Gunicorn per deployment
├── requirements.txt           # Dipendenze Python
├── templates/                 # Template HTML Flask
│   ├── base.html             # Template base ereditato
│   ├── index.html            # Homepage
│   ├── login.html            # Pagina login
│   ├── signup.html           # Pagina registrazione
│   ├── user.html             # Dashboard utente
│   ├── change_password.html   # Cambio password
│   ├── shirts.html           # Catalogo maglie
│   ├── shoes.html            # Catalogo scarpe
│   ├── sports.html           # Articoli sportivi
│   ├── coffee.html           # Bevande/Caffetteria
│   ├── single_shirt.html      # Dettaglio prodotto
│   ├── admin.html            # Dashboard admin
│   ├── admin_users.html      # Gestione utenti admin
│   └── admin_maglie.html      # Gestione maglie admin
├── static/                    # Asset statici
│   ├── style.css             # Stylesheet principale
│   ├── images/               # Immagini statiche
│   │   └── logo/             # Logo e branding
│   └── uploads/              # Cartella upload immagini prodotti
└── test/                      # Moduli test
    └── send_email.py         # Test funzionalità email
```

## Sicurezza

- Password hashate con werkzeug.security.generate_password_hash
- Sessioni persistenti con scadenza impostata
- Cookie HTTPOnly per protezione XSS
- Cookie Secure in produzione
- CSRF protection con SameSite policy
- Validazione input su form
- Gestione errori database sicura

## Performance

- Connection pooling per ridurre overhead connessioni
- Pool ricyclato per prevenire connessioni stantie
- Pre-ping connection per validità connessioni
- Query ottimizzate
- Asset statici serviti da WhiteNoise
- Timeout Gunicorn di 120 secondi per operazioni lunghe
- 8 worker sync per gestione richieste concorrenti

## Logging

- Log configurato per stdout
- Debug output per operazioni database
- Informazioni pool connection su startup

## Installazione e Setup

### Prerequisiti

- Python 3.11+
- PostgreSQL (oppure account Supabase)
- pip per gestione dipendenze
- (Opzionale) Account SMTP per invio email

### Setup Locale

1. **Clonare il repository**
   ```bash
   git clone <repository-url>
   cd OgniPassaggioConta
   ```

2. **Creare ambiente virtuale Python**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Su Windows: venv\Scripts\activate
   ```

3. **Configurare le variabili d'ambiente**
   Creare un file `.env` nella root:
   ```
   SECRET_KEY=your-secret-key-here-change-in-production
   DATABASE_URL=postgresql://user:password@host:5432/dbname
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USERNAME=your-email@gmail.com
   MAIL_PASSWORD=your-app-password
   MAIL_USE_TLS=True
   FLASK_ENV=development
   ```

4. **Installare dipendenze Python**
   ```bash
   pip install -r requirements.txt
   ```

5. **Eseguire l'applicazione localmente**
   ```bash
   python main.py
   ```
   L'applicazione sarà disponibile su `http://localhost:5000`

### Deployment su Render

1. **Connettere repository a Render**
   - Push il codice su GitHub/GitLab
   - Collegare repository su Render dashboard
   - Scegliere Python 3.11 come runtime

2. **Configurare variabili d'ambiente su Render**
   - Aggiungerle nel tab Environment di Render
   - DATABASE_URL dal Supabase
   - SECRET_KEY casuale e sicura

3. **Deploy**
   - Render auto-deploya su git push
   - Procfile specifica il comando di avvio

### Deployment su Heroku (Legacy)

```bash
heroku login
heroku create nome-app
heroku config:set DATABASE_URL=postgresql://...
heroku config:set SECRET_KEY=your-secret-key
git push heroku main
heroku logs --tail
```

## Variabili d'Ambiente Richieste

| Variabile | Descrizione | Obbligatoria |
|-----------|----------|---|
| `SECRET_KEY` | Chiave segreta per sessioni Flask | Si |
| `DATABASE_URL` | Connection string PostgreSQL (Supabase) | Si |
| `MAIL_SERVER` | Server SMTP per email | No |
| `MAIL_PORT` | Porta SMTP (solitamente 587) | No |
| `MAIL_USERNAME` | Email mittente | No |
| `MAIL_PASSWORD` | Password app email | No |
| `MAIL_USE_TLS` | Abilita TLS per email | No |
| `FLASK_ENV` | Ambiente (development/production) | No |

## Struttura Dati Chiave

### Utente
- Email, password hashata, nome, profilo personale
- Data registrazione, ultimo accesso
- Ruolo (user/admin)

### Prodotto
- Nome, descrizione, categoria
- Prezzo, stock disponibile
- Immagini associate
- Data creazione/modifica

### Categoria
- Maglie (shirts)
- Scarpe (shoes)
- Articoli sportivi (sports)
- Bevande (coffee)

## Guida Amministratore

### Accesso Area Admin
1. Login con credenziali admin
2. Accedere a `/admin` dalla dashboard
3. Visualizzare dashboard amministrazione

### Gestione Utenti
- Visualizzare lista utenti completa
- Modificare dati utente
- Eliminare account

### Gestione Prodotti
- Aggiungi nuova maglia/articolo
- Modifica dettagli prodotto
- Gestisci immagini prodotto
- Aggiorna stock e prezzi

## Database Schema

L'applicazione utilizza PostgreSQL con le seguenti tabelle principali:
- `users` - Gestione account utenti
- `products` - Catalogo prodotti
- `categories` - Categorie prodotti
- `sessions` - Sessioni persistenti Flask

## Troubleshooting

### Errore connessione database
- Verificare DATABASE_URL in variabili d'ambiente
- Controllare credenziali PostgreSQL
- Validare IP whitelist su Supabase

### Errore upload immagini
- Verificare permessi directory `static/uploads`
- Controllare limiti dimensione file
- Validare formato immagine

### Errore email
- Verificare credenziali SMTP
- Controllare porta SMTP (587 per TLS)
- Validare app-specific password se usi Gmail

## Licenza

Progetto privato. Tutti i diritti riservati.
