const map = L.map('map').setView([52.2297, 21.0122], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);

let marker = null;
let trajectoryLayer = null;

const $ = (id) => document.getElementById(id);
const latInput = $('lat');
const lonInput = $('lon');
const message = $('message');

function setMessage(text) { message.textContent = text; }
function setPoint(lat, lon) {
  latInput.value = Number(lat).toFixed(5);
  lonInput.value = Number(lon).toFixed(5);
  if (marker) marker.setLatLng([lat, lon]);
  else marker = L.marker([lat, lon]).addTo(map).bindPopup('Точка старта').openPopup();
}

map.on('click', (e) => setPoint(e.latlng.lat, e.latlng.lng));

function defaultDateTime() {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  $('start-time').value = local.toISOString().slice(0, 16);
}
defaultDateTime();
setPoint(52.2297, 21.0122);

function isoTime() {
  const value = $('start-time').value;
  if (!value) throw new Error('Укажите время старта.');
  return new Date(value).toISOString();
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

$('wind-btn').addEventListener('click', async () => {
  try {
    setMessage('Получаю ветер...');
    const lat = Number(latInput.value), lon = Number(lonInput.value);
    const altitude = Number($('start-altitude').value);
    const data = await api(`/api/wind?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&altitude=${encodeURIComponent(altitude)}`);
    $('wind').textContent = `Ветер: ${Number(data.wind_speed).toFixed(1)} м/с, направление ${Number(data.wind_direction).toFixed(0)}°`;
    setMessage('Готово.');
  } catch (e) { setMessage(`Ошибка: ${e.message}`); }
});

$('trajectory-btn').addEventListener('click', async () => {
  const button = $('trajectory-btn');
  try {
    button.disabled = true;
    setMessage('Рассчитываю траекторию...');
    const payload = {
      start: { lat: Number(latInput.value), lon: Number(lonInput.value) },
      start_time: isoTime(),
      start_altitude: Number($('start-altitude').value),
      ascent_rate: Number($('ascent-rate').value),
      max_altitude: Number($('max-altitude').value),
      duration_hours: Number($('duration').value),
      step_minutes: Number($('step').value)
    };
    const data = await api('/api/trajectory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    drawTrajectory(data);
    setMessage(`Готово: ${data.points?.length ?? data.trajectory?.length ?? 0} точек.`);
  } catch (e) { setMessage(`Ошибка: ${e.message}`); }
  finally { button.disabled = false; }
});

function drawTrajectory(data) {
  const points = data.points || data.trajectory || data.path || [];
  if (!Array.isArray(points) || points.length === 0) throw new Error('API не вернул точки траектории.');
  const latlngs = points.map(p => [p.lat, p.lon]);
  if (trajectoryLayer) map.removeLayer(trajectoryLayer);
  trajectoryLayer = L.polyline(latlngs, { weight: 4 }).addTo(map);
  map.fitBounds(trajectoryLayer.getBounds(), { padding: [30, 30] });
  const tbody = $('points-table').querySelector('tbody');
  tbody.innerHTML = '';
  for (const p of points) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${new Date(p.time).toLocaleString()}</td><td>${Number(p.lat).toFixed(4)}</td><td>${Number(p.lon).toFixed(4)}</td><td>${Number(p.altitude ?? p.altitude_m ?? 0).toFixed(0)}</td><td>${Number(p.wind_speed ?? p.wind_speed_mps ?? 0).toFixed(1)}</td><td>${Number(p.wind_direction ?? 0).toFixed(0)}</td>`;
    tbody.appendChild(tr);
  }
  $('summary').textContent = `Траектория рассчитана. Начало: ${new Date(points[0].time).toLocaleString()}, конец: ${new Date(points[points.length - 1].time).toLocaleString()}.`;
}

api('/api/health').then(() => $('health').textContent = 'API работает').catch(() => $('health').textContent = 'API недоступен');
