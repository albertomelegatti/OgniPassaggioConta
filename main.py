from flask import Flask, render_template, request
from flask.cli import load_dotenv
from psycopg2.extras import RealDictCursor
from db import get_connection, release_connection, init_pool
import os

load_dotenv()
init_pool()

app = Flask(__name__)



@app.route('/')
def landing():
    return render_template('index.html')


@app.route('/sports')
def sports():
    return render_template('sports.html')


@app.route('/shirts/<sport>')
def shirts(sport):
    
    print(f"Fetching shirts for sport: {sport}")
    
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    shirts = []
    try:
        cur.execute('''
                       SELECT asta.id, asta.data_inizio, asta.data_fine, asta.offerta_attuale, asta.vincitore_attuale, 
                              maglia.id as maglia_id, maglia.titolo, maglia.descrizione, maglia.prezzo_base, maglia.sport
                       FROM maglia
                       LEFT JOIN asta ON asta.id_maglia = maglia.id
                       WHERE maglia.sport = %s
                       ORDER BY asta.data_fine DESC NULLS LAST
                ''',(sport.lower(),))
        
        shirts_raw = cur.fetchall()
        print(shirts_raw)
        
        for shirt in shirts_raw:
            shirts.append({
                'id': shirt['id'],
                'maglia_id': shirt['maglia_id'],
                'athlete': shirt['titolo'],
                # 'description': shirt['descrizione'],
                'base_price': shirt['prezzo_base'],
                'current_price': shirt['offerta_attuale'],
                # 'start_time': shirt['data_inizio'],
                'end_time': shirt['data_fine'],
                'current_winner': shirt['vincitore_attuale'],
                'has_auction': shirt['id'] is not None
            })
            
        print(shirts)
        
    except Exception as e:
        print(f"Error fetching shirts: {e}")
        
    finally:
        release_connection(conn, cur)
    
    return render_template('shirts.html', sport=sport, shirts=shirts)










@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/signup')
def signup():
    return render_template('signup.html')


@app.route('/admin')
def admin_dashboard():
    return render_template('admin.html')


@app.route('/health')
def health():
    return {'status': 'ok'}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
