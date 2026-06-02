#!/usr/bin/env python3
"""
Saunavuoro - Taloyhtiön saunanvarausjärjestelmä
Raspberry Pi -pohjainen Flask-sovellus
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import sqlite3
import os
from typing import Dict, Tuple, List

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
                heating_power_kw REAL NOT NULL DEFAULT 9.0,      -- Sauna heater kW alussa
                heating_duration_minutes INTEGER NOT NULL DEFAULT 120,  -- Lämmitysaika ennen 1. varausta (min)
                cooling_power_per_hour_kw REAL NOT NULL DEFAULT 5.0,  -- kW/h jäähdytys
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
                heating_cost REAL,
                cooling_cost REAL,
                water_cost REAL,
                total_price REAL,
                status TEXT DEFAULT 'confirmed',  -- confirmed, cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resident_id) REFERENCES residents(id)
            );
            
            -- Hinnan historiikki (audit trail)
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                heating_cost REAL NOT NULL,
                cooling_cost REAL NOT NULL,
                water_cost REAL NOT NULL,
                total_price REAL NOT NULL,
                concurrent_residents INTEGER NOT NULL,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id)
            );
        ''')
        db.commit()

class PricingCalculator:
    """Hintojen laskeminen saunavuoroille"""
    
    def __init__(self, db_row: sqlite3.Row):
        """Alusta laskin hintatiedoilla"""
        self.electricity_per_kw = float(db_row['electricity_per_kw'])
        self.water_per_m3 = float(db_row['water_per_m3'])
        self.heating_power_kw = float(db_row['heating_power_kw'])
        self.heating_duration_minutes = int(db_row['heating_duration_minutes'])
        self.cooling_power_per_hour_kw = float(db_row['cooling_power_per_hour_kw'])
        self.water_consumption_per_hour = float(db_row['water_consumption_per_hour'])
    
    def calculate_heating_cost(self, concurrent_residents: int) -> float:
        """
        Laske lämmityskustannus
        
        Sauna lämpenee 2h ennen ensimmäistä varausta 9kW:lla.
        Kustannus jaetaan kaikkien samalla päivällä varanneiden kesken.
        
        Args:
            concurrent_residents: Kuinka monta asukasta varaukselle samalla päivällä
            
        Returns:
            Lämmityskustannus per varaus (€)
        """
        if concurrent_residents < 1:
            concurrent_residents = 1
        
        # Lämmitysenergia: 9 kW * 2 tunti
        heating_hours = self.heating_duration_minutes / 60
        heating_energy_kwh = self.heating_power_kw * heating_hours
        
        # Lämmityskustannus yhteensä
        total_heating_cost = heating_energy_kwh * self.electricity_per_kw
        
        # Jaa kaikkien asukkaiden kesken
        cost_per_resident = total_heating_cost / concurrent_residents
        
        return round(cost_per_resident, 2)
    
    def calculate_cooling_cost(self, cooling_duration_hours: float, concurrent_residents: int) -> float:
        """
        Laske jäähdytyksen kustannus
        
        Jäähdytys tapahtuu varausten välillä. Kustannus jaetaan
        kaikkien samalla päivällä varanneiden kesken.
        
        Args:
            cooling_duration_hours: Kuinka monta tuntia jäähdytystä
            concurrent_residents: Kuinka monta asukasta varaukselle samalla päivällä
            
        Returns:
            Jäähdytyksen kustannus per varaus (€)
        """
        if concurrent_residents < 1:
            concurrent_residents = 1
        
        if cooling_duration_hours <= 0:
            return 0.0
        
        # Jäähdytysenergia: 5 kW/h * tunteja
        cooling_energy_kwh = self.cooling_power_per_hour_kw * cooling_duration_hours
        
        # Jäähdytyksen kustannus yhteensä
        total_cooling_cost = cooling_energy_kwh * self.electricity_per_kw
        
        # Jaa kaikkien asukkaiden kesken
        cost_per_resident = total_cooling_cost / concurrent_residents
        
        return round(cost_per_resident, 2)
    
    def calculate_water_cost(self, duration_minutes: int) -> float:
        """
        Laske vesikustannus
        
        Vesi kulutetaan varauksen keston mukaan.
        
        Args:
            duration_minutes: Varauksen kesto minuuteissa
            
        Returns:
            Vesikustannus (€)
        """
        duration_hours = duration_minutes / 60
        water_consumption_m3 = self.water_consumption_per_hour * duration_hours
        water_cost = water_consumption_m3 * self.water_per_m3
        
        return round(water_cost, 2)
    
    def calculate_total_price(
        self, 
        duration_minutes: int,
        cooling_duration_hours: float,
        concurrent_residents: int
    ) -> Tuple[float, float, float, float]:
        """
        Laske kokonaishinta varaaukselle
        
        Args:
            duration_minutes: Varauksen kesto minuuteissa
            cooling_duration_hours: Jäähdytysaika ennen seuraavaa varausta
            concurrent_residents: Kuinka monta asukasta samalla päivällä
            
        Returns:
            Tuple: (total_price, heating_cost, cooling_cost, water_cost)
        """
        heating_cost = self.calculate_heating_cost(concurrent_residents)
        cooling_cost = self.calculate_cooling_cost(cooling_duration_hours, concurrent_residents)
        water_cost = self.calculate_water_cost(duration_minutes)
        total_price = heating_cost + cooling_cost + water_cost
        
        return round(total_price, 2), heating_cost, cooling_cost, water_cost

def get_same_day_residents(db, start_time: str) -> int:
    """
    Laske kuinka monta erilaista asukasta on varauksia samalla päivällä
    
    Args:
        db: Tietokantayhteys
        start_time: Varauksen alkamisaika (ISO 8601)
        
    Returns:
        Erilaisten asukkaiden määrä samalla päivällä
    """
    # Erota päivä
    booking_date = start_time.split('T')[0]
    start_of_day = f"{booking_date} 00:00:00"
    end_of_day = f"{booking_date} 23:59:59"
    
    result = db.execute('''
        SELECT COUNT(DISTINCT resident_id) as count FROM bookings 
        WHERE status = 'confirmed'
        AND start_time >= ?
        AND start_time < date(?, '+1 day')
    ''', (start_of_day, booking_date)).fetchone()
    
    # +1 koska laskemme myös uutta varausta
    return result['count'] + 1

def check_overlapping_booking(db, start_time: str, end_time: str, exclude_booking_id: int = None) -> bool:
    """
    Tarkista onko varauksia samaan aikaan (ei sallittua)
    
    Args:
        db: Tietokantayhteys
        start_time: Varauksen alkamisaika (ISO 8601)
        end_time: Varauksen päättymisaika (ISO 8601)
        exclude_booking_id: Poistetaan tämä varaus tarkastuksesta
        
    Returns:
        True jos on päällekkäisyys, False jos ei
    """
    query = '''
        SELECT COUNT(*) as count FROM bookings 
        WHERE status = 'confirmed'
        AND NOT (end_time <= ? OR start_time >= ?)
    '''
    params = [start_time, end_time]
    
    if exclude_booking_id:
        query += ' AND id != ?'
        params.append(exclude_booking_id)
    
    result = db.execute(query, params).fetchone()
    return result['count'] > 0

def calculate_cooling_duration(db, end_time: str) -> float:
    """
    Laske jäähdytysaika seuraavaan varaukseen
    
    Args:
        db: Tietokantayhteys
        end_time: Varauksen päättymisaika (ISO 8601)
        
    Returns:
        Jäähdytysaika tunteina (0 jos ei seuraavaa)
    """
    # Etsi seuraava varaus samalla päivällä
    result = db.execute('''
        SELECT MIN(start_time) as next_start FROM bookings 
        WHERE status = 'confirmed'
        AND start_time > ?
        AND DATE(start_time) = DATE(?)
    ''', (end_time, end_time)).fetchone()
    
    if not result['next_start']:
        return 0.0
    
    next_start = datetime.fromisoformat(result['next_start'])
    current_end = datetime.fromisoformat(end_time)
    
    cooling_duration = (next_start - current_end).total_seconds() / 3600
    
    # Ei negatiivista jäähdytystä
    return max(0.0, cooling_duration)

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
               cooling_power_per_hour_kw = ?,
               water_consumption_per_hour = ?
               WHERE id = 1''',
            (data['electricity_per_kw'], 
             data['water_per_m3'],
             data['heating_power_kw'],
             data['heating_duration_minutes'],
             data['cooling_power_per_hour_kw'],
             data['water_consumption_per_hour'])
        )
        db.commit()
        return jsonify({'status': 'success'})
    
    pricing = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
    if not pricing:
        # Luodaan oletushinnat
        db.execute(
            '''INSERT INTO pricing 
               (electricity_per_kw, water_per_m3, heating_power_kw, 
                heating_duration_minutes, cooling_power_per_hour_kw, water_consumption_per_hour) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (0.30, 2.50, 9.0, 120, 5.0, 0.05)
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
        
        # Validointi
        try:
            start_time = datetime.fromisoformat(data['start_time'])
            end_time = datetime.fromisoformat(data['end_time'])
            resident_id = int(data['resident_id'])
            
            # Tarkista että varaus on tulevaisuudessa
            now = datetime.now()
            if start_time <= now:
                return jsonify({'error': 'Varaus täytyy olla tulevaisuudessa'}), 400
            
            # Tarkista että varaus on 2h päähän
            min_booking_time = now + timedelta(hours=2)
            if start_time < min_booking_time:
                return jsonify({'error': 'Varaus täytyy olla vähintään 2h päähän'}), 400
            
            # Tarkista että varaus on maksimissaan 1 kuukauden päähän
            max_booking_time = now + timedelta(days=30)
            if start_time > max_booking_time:
                return jsonify({'error': 'Varaus täytyy olla enintään 1 kuukauden päähän'}), 400
            
            # Laske varauksen kesto
            duration_minutes = int((end_time - start_time).total_seconds() / 60)
            
            if duration_minutes < 60:
                return jsonify({'error': 'Varaus täytyy olla vähintään 1 tunti'}), 400
            
            # Tarkista että ei ole päällekkäisiä varauksia
            if check_overlapping_booking(db, data['start_time'], data['end_time']):
                return jsonify({'error': 'Saunaa ei voi varata päällekkäisille ajoille'}), 400
            
            # Laske kuinka monta asukasta samalla päivällä
            concurrent_residents = get_same_day_residents(db, data['start_time'])
            
            # Laske jäähdytysaika
            cooling_duration = calculate_cooling_duration(db, data['end_time'])
            
            # Laske hinta
            pricing_data = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
            calculator = PricingCalculator(pricing_data)
            total_price, heating_cost, cooling_cost, water_cost = calculator.calculate_total_price(
                duration_minutes,
                cooling_duration,
                concurrent_residents
            )
            
            # Tallenna varaus
            cursor = db.execute(
                '''INSERT INTO bookings 
                   (resident_id, start_time, end_time, duration_minutes, 
                    heating_cost, cooling_cost, water_cost, total_price, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed')''',
                (resident_id, data['start_time'], data['end_time'], duration_minutes,
                 heating_cost, cooling_cost, water_cost, total_price)
            )
            booking_id = cursor.lastrowid
            db.commit()
            
            # Tallenna hinnan historiikki
            db.execute(
                '''INSERT INTO price_history 
                   (booking_id, heating_cost, cooling_cost, water_cost, 
                    total_price, concurrent_residents) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (booking_id, heating_cost, cooling_cost, water_cost, 
                 total_price, concurrent_residents)
            )
            db.commit()
            
            return jsonify({
                'status': 'success',
                'booking_id': booking_id,
                'heating_cost': heating_cost,
                'cooling_cost': cooling_cost,
                'water_cost': water_cost,
                'total_price': total_price,
                'concurrent_residents': concurrent_residents
            }), 201
            
        except ValueError as e:
            return jsonify({'error': f'Virheellinen syöte: {str(e)}'}), 400
        except Exception as e:
            return jsonify({'error': f'Virhe varauksen luomisessa: {str(e)}'}), 500
    
    bookings = db.execute('''
        SELECT b.*, r.name, r.apartment 
        FROM bookings b 
        LEFT JOIN residents r ON b.resident_id = r.id
        WHERE b.status = 'confirmed' 
        ORDER BY b.start_time
    ''').fetchall()
    return jsonify([dict(b) for b in bookings])

@app.route('/api/pricing/preview', methods=['POST'])
def pricing_preview():
    """
    Ennakkoarvio hinnasta ennen varauksen tekemistä
    
    POST data: {
        "start_time": "2024-06-15T14:00:00",
        "end_time": "2024-06-15T15:00:00"
    }
    """
    db = get_db()
    data = request.get_json()
    
    try:
        duration_minutes = int(
            (datetime.fromisoformat(data['end_time']) - 
             datetime.fromisoformat(data['start_time'])).total_seconds() / 60
        )
        
        concurrent_residents = get_same_day_residents(db, data['start_time'])
        cooling_duration = calculate_cooling_duration(db, data['end_time'])
        
        pricing_data = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
        calculator = PricingCalculator(pricing_data)
        total_price, heating_cost, cooling_cost, water_cost = calculator.calculate_total_price(
            duration_minutes,
            cooling_duration,
            concurrent_residents
        )
        
        return jsonify({
            'total_price': total_price,
            'heating_cost': heating_cost,
            'cooling_cost': cooling_cost,
            'water_cost': water_cost,
            'concurrent_residents': concurrent_residents,
            'cooling_duration': cooling_duration,
            'duration_minutes': duration_minutes
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    # Alusta tietokanta
    if not os.path.exists(app.config['DATABASE']):
        init_db()
    
    # Käynnistä Flask
    app.run(host='0.0.0.0', port=5000, debug=True)
