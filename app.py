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
                heating_power_kw REAL NOT NULL DEFAULT 9.0,      -- Sauna heater kW alkulämmityksessä
                heating_duration_minutes INTEGER NOT NULL DEFAULT 120,  -- Lämmitysaika ennen 1. varausta (min)
                maintenance_power_per_hour_kw REAL NOT NULL DEFAULT 5.0,  -- kW/h käynnissäpitoon varausten välillä
                water_consumption_per_hour REAL NOT NULL DEFAULT 0.05,  -- m³/h
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Varaukset
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resident_id INTEGER NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                actual_end_time TIMESTAMP,  -- Todellinen loppumisaika kun merkattiin vapaaksi
                duration_minutes INTEGER NOT NULL,
                heating_cost REAL,
                maintenance_cost REAL,
                water_cost REAL,
                total_price REAL,
                status TEXT DEFAULT 'confirmed',  -- confirmed, in_progress, completed, cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resident_id) REFERENCES residents(id)
            );
            
            -- Hinnan historiikki (audit trail)
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                heating_cost REAL NOT NULL,
                maintenance_cost REAL NOT NULL,
                water_cost REAL NOT NULL,
                total_price REAL NOT NULL,
                concurrent_residents INTEGER NOT NULL,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id)
            );
            
            -- Saunan tila
            CREATE TABLE IF NOT EXISTS sauna_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'off',  -- off, heating, ready, in_use
                current_booking_id INTEGER,
                active_residents INTEGER DEFAULT 0,  -- Kuinka monta asukasta on varannut saunaa tänään
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (current_booking_id) REFERENCES bookings(id)
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
        self.maintenance_power_per_hour_kw = float(db_row['maintenance_power_per_hour_kw'])
        self.water_consumption_per_hour = float(db_row['water_consumption_per_hour'])
    
    def calculate_heating_cost(self, concurrent_residents: int) -> float:
        """
        Laske alkulämmityskustannus
        
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
    
    def calculate_maintenance_cost(self, maintenance_duration_hours: float, concurrent_residents: int) -> float:
        """
        Laske käynnissäpidon kustannus
        
        Sauna pidetään lämpimänä varausten välillä. Kustannus jaetaan
        kaikkien samalla päivällä varanneiden kesken.
        
        Args:
            maintenance_duration_hours: Kuinka monta tuntia käynnissäpitoa
            concurrent_residents: Kuinka monta asukasta varaukselle samalla päivällä
            
        Returns:
            Käynnissäpidon kustannus per varaus (€)
        """
        if concurrent_residents < 1:
            concurrent_residents = 1
        
        if maintenance_duration_hours <= 0:
            return 0.0
        
        # Käynnissäpitoenergia: ~5 kW/h * tunteja
        maintenance_energy_kwh = self.maintenance_power_per_hour_kw * maintenance_duration_hours
        
        # Käynnissäpidon kustannus yhteensä
        total_maintenance_cost = maintenance_energy_kwh * self.electricity_per_kw
        
        # Jaa kaikkien asukkaiden kesken
        cost_per_resident = total_maintenance_cost / concurrent_residents
        
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
        maintenance_duration_hours: float,
        concurrent_residents: int
    ) -> Tuple[float, float, float, float]:
        """
        Laske kokonaishinta varaaukselle
        
        Args:
            duration_minutes: Varauksen kesto minuuteissa
            maintenance_duration_hours: Käynnissäpitoaika seuraavaan varaukseen
            concurrent_residents: Kuinka monta asukasta samalla päivällä
            
        Returns:
            Tuple: (total_price, heating_cost, maintenance_cost, water_cost)
        """
        heating_cost = self.calculate_heating_cost(concurrent_residents)
        maintenance_cost = self.calculate_maintenance_cost(maintenance_duration_hours, concurrent_residents)
        water_cost = self.calculate_water_cost(duration_minutes)
        total_price = heating_cost + maintenance_cost + water_cost
        
        return round(total_price, 2), heating_cost, maintenance_cost, water_cost

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
        WHERE status IN ('confirmed', 'in_progress', 'completed')
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
        WHERE status IN ('confirmed', 'in_progress')
        AND NOT (end_time <= ? OR start_time >= ?)
    '''
    params = [start_time, end_time]
    
    if exclude_booking_id:
        query += ' AND id != ?'
        params.append(exclude_booking_id)
    
    result = db.execute(query, params).fetchone()
    return result['count'] > 0

def calculate_maintenance_duration(db, end_time: str) -> float:
    """
    Laske käynnissäpitoaika seuraavaan varaukseen
    
    Args:
        db: Tietokantayhteys
        end_time: Varauksen päättymisaika (ISO 8601)
        
    Returns:
        Käynnissäpitoaika tunteina (0 jos ei seuraavaa)
    """
    # Etsi seuraava varaus samalla päivällä
    result = db.execute('''
        SELECT MIN(start_time) as next_start FROM bookings 
        WHERE status IN ('confirmed', 'in_progress')
        AND start_time > ?
        AND DATE(start_time) = DATE(?)
    ''', (end_time, end_time)).fetchone()
    
    if not result['next_start']:
        return 0.0
    
    next_start = datetime.fromisoformat(result['next_start'])
    current_end = datetime.fromisoformat(end_time)
    
    maintenance_duration = (next_start - current_end).total_seconds() / 3600
    
    # Ei negatiivista käynnissäpitoa
    return max(0.0, maintenance_duration)

def is_last_booking_of_day(db, booking_id: int) -> bool:
    """
    Tarkista onko tämä viimeinen varaus päivällä
    
    Args:
        db: Tietokantayhteys
        booking_id: Varauksen ID
        
    Returns:
        True jos tämä on viimeinen varaus
    """
    booking = db.execute('SELECT start_time FROM bookings WHERE id = ?', (booking_id,)).fetchone()
    if not booking:
        return False
    
    booking_date = booking['start_time'].split(' ')[0]
    
    result = db.execute('''
        SELECT COUNT(*) as count FROM bookings 
        WHERE status IN ('confirmed', 'in_progress')
        AND DATE(start_time) = ?
        AND id != ?
    ''', (booking_date, booking_id)).fetchone()
    
    return result['count'] == 0

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
               maintenance_power_per_hour_kw = ?,
               water_consumption_per_hour = ?
               WHERE id = 1''',
            (data['electricity_per_kw'], 
             data['water_per_m3'],
             data['heating_power_kw'],
             data['heating_duration_minutes'],
             data['maintenance_power_per_hour_kw'],
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
                heating_duration_minutes, maintenance_power_per_hour_kw, water_consumption_per_hour) 
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
            
            # Laske käynnissäpitoaika
            maintenance_duration = calculate_maintenance_duration(db, data['end_time'])
            
            # Laske hinta
            pricing_data = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
            calculator = PricingCalculator(pricing_data)
            total_price, heating_cost, maintenance_cost, water_cost = calculator.calculate_total_price(
                duration_minutes,
                maintenance_duration,
                concurrent_residents
            )
            
            # Tallenna varaus
            cursor = db.execute(
                '''INSERT INTO bookings 
                   (resident_id, start_time, end_time, duration_minutes, 
                    heating_cost, maintenance_cost, water_cost, total_price, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed')''',
                (resident_id, data['start_time'], data['end_time'], duration_minutes,
                 heating_cost, maintenance_cost, water_cost, total_price)
            )
            booking_id = cursor.lastrowid
            db.commit()
            
            # Tallenna hinnan historiikki
            db.execute(
                '''INSERT INTO price_history 
                   (booking_id, heating_cost, maintenance_cost, water_cost, 
                    total_price, concurrent_residents) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (booking_id, heating_cost, maintenance_cost, water_cost, 
                 total_price, concurrent_residents)
            )
            db.commit()
            
            return jsonify({
                'status': 'success',
                'booking_id': booking_id,
                'heating_cost': heating_cost,
                'maintenance_cost': maintenance_cost,
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
        WHERE b.status IN ('confirmed', 'in_progress', 'completed')
        ORDER BY b.start_time
    ''').fetchall()
    return jsonify([dict(b) for b in bookings])

@app.route('/api/bookings/<int:booking_id>/start', methods=['POST'])
def start_booking(booking_id: int):
    """Merkitse varaus alkaneeksi"""
    db = get_db()
    
    try:
        booking = db.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
        
        if not booking:
            return jsonify({'error': 'Varausta ei löydy'}), 404
        
        if booking['status'] != 'confirmed':
            return jsonify({'error': 'Vain confirmed-varauksen voi merkitä alkaneeksi'}), 400
        
        # Päivitä varauksen status
        db.execute('UPDATE bookings SET status = ? WHERE id = ?', ('in_progress', booking_id))
        db.commit()
        
        return jsonify({
            'status': 'success',
            'message': f"Varaus #{booking_id} merkitty alkaneeksi"
        })
    except Exception as e:
        return jsonify({'error': f'Virhe: {str(e)}'}), 500

@app.route('/api/bookings/<int:booking_id>/complete', methods=['POST'])
def complete_booking(booking_id: int):
    """Merkitse varaus vapaaksi ja laske lopullinen hinta"""
    db = get_db()
    
    try:
        booking = db.execute('SELECT * FROM bookings WHERE id = ?', (booking_id,)).fetchone()
        
        if not booking:
            return jsonify({'error': 'Varausta ei löydy'}), 404
        
        if booking['status'] != 'in_progress':
            return jsonify({'error': 'Vain in_progress-varauksen voi merkitä vapaaksi'}), 400
        
        # Merkitse todellinen loppumisaika
        actual_end_time = datetime.now().isoformat()
        
        # Laske todellinen kesto
        start_time = datetime.fromisoformat(booking['start_time'])
        actual_end = datetime.now()
        actual_duration_minutes = int((actual_end - start_time).total_seconds() / 60)
        
        # Päivitä varauksen tiedot
        db.execute('''
            UPDATE bookings 
            SET status = ?, actual_end_time = ?, duration_minutes = ?
            WHERE id = ?
        ''', ('completed', actual_end_time, actual_duration_minutes, booking_id))
        db.commit()
        
        # Tarkista onko tämä viimeinen varaus päivällä
        is_last = is_last_booking_of_day(db, booking_id)
        
        sauna_off = False
        if is_last:
            # Sammuta sauna
            db.execute('UPDATE sauna_status SET status = ? WHERE id = 1', ('off',))
            db.commit()
            sauna_off = True
        
        return jsonify({
            'status': 'success',
            'message': f"Varaus #{booking_id} merkitty vapaaksi",
            'actual_duration': actual_duration_minutes,
            'sauna_off': sauna_off
        })
    except Exception as e:
        return jsonify({'error': f'Virhe: {str(e)}'}), 500

@app.route('/api/sauna/status', methods=['GET'])
def sauna_status():
    """Hae saunan tila"""
    db = get_db()
    
    try:
        status = db.execute('SELECT * FROM sauna_status WHERE id = 1').fetchone()
        
        if not status:
            # Luo oletusstatus
            db.execute('''
                INSERT INTO sauna_status (status, active_residents) 
                VALUES (?, ?)
            ''', ('off', 0))
            db.commit()
            status = db.execute('SELECT * FROM sauna_status WHERE id = 1').fetchone()
        
        # Laske aktiiviset varaukset tänään
        today = datetime.now().strftime('%Y-%m-%d')
        active_bookings = db.execute('''
            SELECT COUNT(*) as count FROM bookings 
            WHERE status IN ('confirmed', 'in_progress')
            AND DATE(start_time) = ?
        ''', (today,)).fetchone()
        
        return jsonify({
            'status': status['status'],
            'active_residents': active_bookings['count'],
            'last_updated': status['last_updated']
        })
    except Exception as e:
        return jsonify({'error': f'Virhe: {str(e)}'}), 500

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
        maintenance_duration = calculate_maintenance_duration(db, data['end_time'])
        
        pricing_data = db.execute('SELECT * FROM pricing WHERE id = 1').fetchone()
        calculator = PricingCalculator(pricing_data)
        total_price, heating_cost, maintenance_cost, water_cost = calculator.calculate_total_price(
            duration_minutes,
            maintenance_duration,
            concurrent_residents
        )
        
        return jsonify({
            'total_price': total_price,
            'heating_cost': heating_cost,
            'maintenance_cost': maintenance_cost,
            'water_cost': water_cost,
            'concurrent_residents': concurrent_residents,
            'maintenance_duration': maintenance_duration,
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
