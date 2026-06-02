// Tab navigation
document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', () => {
        const tabName = button.dataset.tab;
        
        // Deactivate all tabs
        document.querySelectorAll('.tab-content').forEach(tab => {
            tab.classList.remove('active');
        });
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.remove('active');
        });
        
        // Activate selected tab
        document.getElementById(tabName).classList.add('active');
        button.classList.add('active');
        
        // Load data
        if (tabName === 'residents') loadResidents();
        if (tabName === 'pricing') loadPricing();
        if (tabName === 'bookings') loadBookings();
    });
});

// Load residents
async function loadResidents() {
    try {
        const response = await fetch('/api/residents');
        const residents = await response.json();
        const list = document.getElementById('residents-list');
        
        list.innerHTML = residents.map(r => `
            <div class="card">
                <h3>${r.name} (${r.apartment})</h3>
                <p>${r.email || ''}</p>
                <p>${r.phone || ''}</p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading residents:', error);
    }
}

// Add resident
document.getElementById('resident-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inputs = e.target.querySelectorAll('input');
    
    try {
        const response = await fetch('/api/residents', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: inputs[0].value,
                apartment: inputs[1].value,
                email: inputs[2].value,
                phone: inputs[3].value
            })
        });
        
        if (response.ok) {
            e.target.reset();
            loadResidents();
            alert('Asukas lisätty!');
        }
    } catch (error) {
        console.error('Error adding resident:', error);
    }
});

// Load pricing
async function loadPricing() {
    try {
        const response = await fetch('/api/pricing');
        const pricing = await response.json();
        
        document.getElementById('electricity').value = pricing.electricity_per_kw;
        document.getElementById('water').value = pricing.water_per_m3;
        document.getElementById('heating_power').value = pricing.heating_power_kw;
        document.getElementById('heating_duration').value = pricing.heating_duration_minutes;
        document.getElementById('water_consumption').value = pricing.water_consumption_per_hour;
    } catch (error) {
        console.error('Error loading pricing:', error);
    }
}

// Save pricing
document.getElementById('pricing-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    try {
        const response = await fetch('/api/pricing', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                electricity_per_kw: parseFloat(document.getElementById('electricity').value),
                water_per_m3: parseFloat(document.getElementById('water').value),
                heating_power_kw: parseFloat(document.getElementById('heating_power').value),
                heating_duration_minutes: parseInt(document.getElementById('heating_duration').value),
                water_consumption_per_hour: parseFloat(document.getElementById('water_consumption').value)
            })
        });
        
        if (response.ok) {
            alert('Hinnat tallennettu!');
        }
    } catch (error) {
        console.error('Error saving pricing:', error);
    }
});

// Load bookings
async function loadBookings() {
    try {
        const response = await fetch('/api/bookings');
        const bookings = await response.json();
        const list = document.getElementById('bookings-list');
        
        if (bookings.length === 0) {
            list.innerHTML = '<p>Ei varauksia</p>';
            return;
        }
        
        list.innerHTML = bookings.map(b => `
            <div class="card">
                <h3>Varaus #${b.id}</h3>
                <p>Asukas ID: ${b.resident_id}</p>
                <p>Aika: ${b.start_time} - ${b.end_time}</p>
                <p>Hinta: ${b.price ? b.price.toFixed(2) : '-'} €</p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading bookings:', error);
    }
}

// Load initial data
loadResidents();
