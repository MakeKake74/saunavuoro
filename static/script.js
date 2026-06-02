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

// Set minimum date to today
document.getElementById('booking-date').min = new Date().toISOString().split('T')[0];

// Load residents dropdown
async function loadResidentsDropdown() {
    try {
        const response = await fetch('/api/residents');
        const residents = await response.json();
        const select = document.getElementById('resident');
        
        residents.forEach(r => {
            const option = document.createElement('option');
            option.value = r.id;
            option.textContent = `${r.name} (${r.apartment})`;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading residents:', error);
    }
}

// Update price preview when form inputs change
function setupPricePreviewListeners() {
    const inputs = ['resident', 'booking-date', 'start-time', 'end-time'];
    inputs.forEach(id => {
        document.getElementById(id).addEventListener('change', updatePricePreview);
    });
}

// Update price preview
async function updatePricePreview() {
    const residentSelect = document.getElementById('resident');
    const date = document.getElementById('booking-date').value;
    const startTime = document.getElementById('start-time').value;
    const endTime = document.getElementById('end-time').value;
    const pricePreview = document.getElementById('price-preview');
    
    if (!date || !startTime || !endTime || !residentSelect.value) {
        pricePreview.classList.add('hidden');
        return;
    }
    
    const startISO = `${date}T${startTime}:00`;
    const endISO = `${date}T${endTime}:00`;
    
    try {
        const response = await fetch('/api/pricing/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                start_time: startISO,
                end_time: endISO
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            document.getElementById('preview-heating').textContent = data.heating_cost.toFixed(2) + ' €';
            document.getElementById('preview-maintenance').textContent = data.maintenance_cost.toFixed(2) + ' €';
            document.getElementById('preview-water').textContent = data.water_cost.toFixed(2) + ' €';
            document.getElementById('preview-total').textContent = data.total_price.toFixed(2) + ' €';
            document.getElementById('preview-residents').textContent = data.concurrent_residents;
            pricePreview.classList.remove('hidden');
        } else {
            pricePreview.classList.add('hidden');
        }
    } catch (error) {
        console.error('Error updating price preview:', error);
        pricePreview.classList.add('hidden');
    }
}

// Book sauna
document.getElementById('booking-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const messageDiv = document.getElementById('booking-message');
    
    const residentId = document.getElementById('resident').value;
    const date = document.getElementById('booking-date').value;
    const startTime = document.getElementById('start-time').value;
    const endTime = document.getElementById('end-time').value;
    
    const startISO = `${date}T${startTime}:00`;
    const endISO = `${date}T${endTime}:00`;
    
    try {
        const response = await fetch('/api/bookings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                resident_id: parseInt(residentId),
                start_time: startISO,
                end_time: endISO
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            messageDiv.textContent = `✅ Varaus onnistui! Hinta: ${data.total_price.toFixed(2)} €`;
            messageDiv.className = 'success';
            messageDiv.classList.remove('hidden');
            e.target.reset();
            document.getElementById('price-preview').classList.add('hidden');
            setTimeout(() => {
                messageDiv.classList.add('hidden');
                loadBookings();
            }, 3000);
        } else {
            messageDiv.textContent = `❌ Virhe: ${data.error}`;
            messageDiv.className = 'error';
            messageDiv.classList.remove('hidden');
        }
    } catch (error) {
        messageDiv.textContent = `❌ Virhe varauksen luomisessa: ${error.message}`;
        messageDiv.className = 'error';
        messageDiv.classList.remove('hidden');
        console.error('Error booking sauna:', error);
    }
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
                <p>📧 ${r.email || 'Ei sähköpostia'}</p>
                <p>📱 ${r.phone || 'Ei puhelinnumeroa'}</p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading residents:', error);
    }
}

// Add resident
document.getElementById('resident-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const name = document.getElementById('resident-name').value;
    const apartment = document.getElementById('resident-apartment').value;
    const email = document.getElementById('resident-email').value;
    const phone = document.getElementById('resident-phone').value;
    
    try {
        const response = await fetch('/api/residents', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name,
                apartment,
                email,
                phone
            })
        });
        
        if (response.ok) {
            e.target.reset();
            loadResidents();
            loadResidentsDropdown();
            alert('✅ Asukas lisätty!');
        } else {
            const data = await response.json();
            alert('❌ Virhe: ' + data.error);
        }
    } catch (error) {
        console.error('Error adding resident:', error);
        alert('❌ Virhe asukaan lisäämisessä');
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
        document.getElementById('maintenance_power').value = pricing.maintenance_power_per_hour_kw;
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
                maintenance_power_per_hour_kw: parseFloat(document.getElementById('maintenance_power').value),
                water_consumption_per_hour: parseFloat(document.getElementById('water_consumption').value)
            })
        });
        
        if (response.ok) {
            alert('✅ Hinnat tallennettu!');
        } else {
            alert('❌ Virhe hintojen tallentamisessa');
        }
    } catch (error) {
        console.error('Error saving pricing:', error);
        alert('❌ Virhe hintojen tallentamisessa');
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
        
        list.innerHTML = bookings.map(b => {
            const startDate = new Date(b.start_time).toLocaleString('fi-FI');
            const endDate = new Date(b.end_time).toLocaleString('fi-FI');
            
            return `
                <div class="card">
                    <h3>${b.name} (${b.apartment})</h3>
                    <p>📅 ${startDate}</p>
                    <p>🕐 Kesto: ${b.duration_minutes} minuuttia</p>
                    <p>💰 Hinta: 
                        <strong>${b.total_price.toFixed(2)} €</strong>
                        (Lämmitys: ${b.heating_cost.toFixed(2)} € + 
                         Käynnissäpito: ${b.maintenance_cost.toFixed(2)} € + 
                         Vesi: ${b.water_cost.toFixed(2)} €)
                    </p>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading bookings:', error);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadResidentsDropdown();
    loadResidents();
    setupPricePreviewListeners();
});
