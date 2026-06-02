#!/usr/bin/env python3
"""
Saunavuoro - Taloyhtiön saunanvarausjärjestelmä
Raspberry Pi -pohjainen Flask-sovellus
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import sqlite3
import os

app = Flask(__name__)
app.config['DATABASE'] = 'saunavuoro.db'

def get_db():
    """Avaa tietokantayhteyden"""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Alustaa tietokannan"""
    db = get_db()
    with app.app_context():
        db.executescript('''
            -- Asukkaat
            CREATE TABLE IF NOT EXISTS residents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                apartment TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Hinnat (konfiguroitavat)
            CREATE TABLE IF NOT EXISTS pricing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                electricity_per_kw REAL NOT NULL DEFAULT 0.30,  -- €/kW
                water_per_m3 REAL NOT NULL DEFAULT 2.50,        -- €/m³
                heating_power_kw REAL NOT NULL DEFAULT 9.0,      -- Sauna heater kW
                heating_duration_minutes INTEGER NOT NULL DEFAULT 120,  -- Min lämmitysaika
                water_consumption_per_hour REAL NOT NULL DEFAULT 0.05,  -- m³/h
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Varaukset
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resident_id INTEGER NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                duration_minutes INTEGER NOT NULL,
                price REAL,
                status TEXT DEFAULT 'confirmed',  -- confirmed, cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resident_id) REFERENCES residents(id)
            );
            
            -- Hinnan historiikki (audit trail)
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                calculated_price REAL NOT NULL,
                heating_cost REAL NOT NULL,
                water_cost REAL NOT NULL,
                concurrent_bookings INTEGER NOT NULL,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id)
            );
        ''')
        db.commit()

@app.route('/')
def index():
    """Etusivu"""
    return render_template('index.html')

@app.route('/api/residents', methods=['GET', 'POST'])
def residents():
    """Asukkaiden hallinta"""
    db = get_db()
    
    if request.method == 'POST':
        data = request.get_json()
        try:
            db.execute(
                'INSERT INTO residents (name, apartment, email, phone) VALUES (?, ?, ?, ?)',
                (data['name'], data['apartment'], data.get('email'), data.get('phone'))
            )
            db.commit()
            return jsonify({'status': 'success'}), 201
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Asukas on jo olemassa'}), 400
    
    residents = db.execute('SELECT * FROM residents ORDER BY name').fetchall()
    return jsonify([dict(r) for r in residents])

@app.route('/api/pricing', methods=['GET', 'POST'])
def pricing():
    """Hintojen hallinta"""
    db = get_db()
    
    if request.method == 'POST':
        data = request.get_json()
        db.execute(
            '''UPDATE pricing SET 
               electricity_per_kw = ?, 
               water_per_m3 = ?,
               heating_power_kw = ?,
               heating_duration_minutes = ?,
               water_consumption_per_hour = ?
               WHERE id = 1''',
            (data['electricity_per_kw'], 
             data['water_per_m3'],
             data['heating_power_kw'],
             data['heating_duration_minutes'],
             data['water_consumption_per_hour'])
        )
        db.commit()
        return jsonify({'status': 'success'})
    
    pricing = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
    if not pricing:
        # Luodaan oletushinnat
        db.execute(
            'INSERT INTO pricing (electricity_per_kw, water_per_m3, heating_power_kw, heating_duration_minutes, water_consumption_per_hour) VALUES (?, ?, ?, ?, ?)',
            (0.30, 2.50, 9.0, 120, 0.05)
        )
        db.commit()
        pricing = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
    
    return jsonify(dict(pricing))

@app.route('/api/bookings', methods=['GET', 'POST'])
def bookings():
    """Varausten hallinta"""
    db = get_db()
    
    if request.method == 'POST':
        data = request.get_json()
        # TODO: Varauksen validointi ja hinnan laskeminen
        return jsonify({'status': 'success'}), 201
    
    bookings = db.execute('SELECT * FROM bookings WHERE status = "confirmed" ORDER BY start_time').fetchall()
    return jsonify([dict(b) for b in bookings])

if __name__ == '__main__':
    # Alusta tietokanta
    if not os.path.exists(app.config['DATABASE']):
        init_db()
    
    # Käynnistä Flask
    app.run(host='0.0.0.0', port=5000, debug=True)
