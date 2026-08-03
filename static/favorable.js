// Режим «Благоприятные условия».
// Подключается после HTML и до основного frontend.
var favMode = null;
var favTargetLat = document.getElementById("fav-target-lat");
var favTargetLon = document.getElementById("fav-target-lon");
var favLaunchLat = document.getElementById("fav-launch-lat");
var favLaunchLon = document.getElementById("fav-launch-lon");
var favTargetMarker = null;
var favLaunchMarker = null;

function favEl(id) { return document.getElementById(id); }

function updateFavTargetMarker(lat, lon) {
    if (typeof map === "undefined" || !map) return;
    if (favTargetMarker) { favTargetMarker.setLatLng([lat, lon]); return; }
    favTargetMarker = L.marker([lat, lon], { draggable: true }).addTo(map);
    favTargetMarker.bindPopup("Целевая точка");
    favTargetMarker.on("dragend", function () {
        var p = favTargetMarker.getLatLng();
        favEl("fav-target-lat").value = p.lat.toFixed(6);
        favEl("fav-target-lon").value = p.lng.toFixed(6);
    });
}

function updateFavLaunchMarker(lat, lon) {
    if (typeof map === "undefined" || !map) return;
    if (favLaunchMarker) { favLaunchMarker.setLatLng([lat, lon]); return; }
    favLaunchMarker = L.marker([lat, lon], { draggable: true }).addTo(map);
    favLaunchMarker.bindPopup("Центр области запуска");
    favLaunchMarker.on("dragend", function () {
        var p = favLaunchMarker.getLatLng();
        favEl("fav-launch-lat").value = p.lat.toFixed(6);
        favEl("fav-launch-lon").value = p.lng.toFixed(6);
    });
}

function setFavorableMode() {
    var directTab = favEl("tab-direct");
    var backTab = favEl("tab-back");
    var favTab = favEl("tab-favorable");
    var directPanel = favEl("direct-panel");
    var backPanel = favEl("back-panel");
    var favPanel = favEl("favorable-panel");
    var mapMode = favEl("map-mode");

    if (directTab) directTab.classList.remove("active");
    if (backTab) backTab.classList.remove("active");
    if (favTab) favTab.classList.add("active");
    if (directPanel) directPanel.classList.add("hidden");
    if (backPanel) backPanel.classList.add("hidden");
    if (favPanel) favPanel.classList.remove("hidden");
    if (mapMode) mapMode.textContent = "Благоприятные условия";
    if (typeof activeMode !== "undefined") activeMode = "favorable";
    if (typeof selectionMode !== "undefined") selectionMode = null;
    favMode = null;
}

function setFavorableStatus(text, error) {
    var status = favEl("status");
    if (!status) return;
    status.textContent = text || "";
    status.classList.toggle("error", !!error);
}

function enableFavTargetSelection() {
    setFavorableMode();
    favMode = "target";
    setFavorableStatus("Кликните по карте, чтобы установить целевую точку.");
}

function enableFavLaunchSelection() {
    setFavorableMode();
    favMode = "launch";
    setFavorableStatus("Кликните по карте, чтобы установить центр области запуска.");
}

function validFavCoordinates(lat, lon) {
    return Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)) && Number(lat) >= -90 && Number(lat) <= 90 && Number(lon) >= -180 && Number(lon) <= 180;
}

async function calculateFavorable() {
    var targetLat = Number(favEl("fav-target-lat")?.value);
    var targetLon = Number(favEl("fav-target-lon")?.value);
    var launchLat = Number(favEl("fav-launch-lat")?.value);
    var launchLon = Number(favEl("fav-launch-lon")?.value);
    if (!validFavCoordinates(targetLat, targetLon) || !validFavCoordinates(launchLat, launchLon)) {
        setFavorableStatus("Проверьте координаты цели и области запуска.", true); return;
    }
    var start = favEl("fav-search-start")?.value;
    var end = favEl("fav-search-end")?.value;
    if (!start || !end) { setFavorableStatus("Укажите начало и конец периода поиска.", true); return; }

    var button = favEl("calculate-favorable");
    if (button) button.disabled = true;
    setFavorableStatus("Ищем благоприятные окна...");
    try {
        var payload = {
            target: { lat: targetLat, lon: targetLon },
            launch_center: { lat: launchLat, lon: launchLon },
            search_start: new Date(start).toISOString(), search_end: new Date(end).toISOString(),
            launch_radius_m: Number(favEl("fav-radius")?.value) || 1000,
            radius_tolerance_m: 100, time_step_hours: 1, window_half_width_hours: 3,
            max_acceptable_distance_m: Number(favEl("fav-max-dist")?.value) || 5000,
            ascent_rate: Number(favEl("fav-ascent")?.value) || 5,
            max_altitude: Number(favEl("fav-max-alt")?.value) || 9000,
            duration_hours: Number(favEl("fav-duration")?.value) || 5,
            step_minutes: 2, start_altitude: 0, points_per_circle: 7
        };
        var response = await fetch("/api/favorable", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        var data = await response.json();
        if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));
        var results = favEl("results");
        var content = favEl("result-content");
        if (results) results.classList.remove("hidden");
        if (!data.windows || !data.windows.length) {
            if (content) content.innerHTML = "<div class='result-card'>Подходящих окон не найдено.</div>";
            setFavorableStatus("Расчёт завершён: подходящих окон не найдено."); return;
        }
        if (content) content.innerHTML = data.windows.map(function (w, i) {
            return '<div class="result-card"><strong>Окно ' + (i + 1) + ': ' + (w.date || "—") + '</strong>' +
                '<div>Период: ' + new Date(w.window_start).toLocaleString("ru-RU") + ' — ' + new Date(w.window_end).toLocaleString("ru-RU") + '</div>' +
                '<div>Рекомендуемый запуск: ' + new Date(w.recommended_time).toLocaleString("ru-RU") + '</div>' +
                '<div>Кандидатов: ' + ((w.best_candidates && w.best_candidates.length) || 0) + '</div></div>';
        }).join("");
        setFavorableStatus("Готово: найдено окон — " + data.windows.length + ".");
    } catch (error) {
        console.error("Ошибка благоприятных условий:", error);
        setFavorableStatus(error.message || "Ошибка расчёта.", true);
    } finally { if (button) button.disabled = false; }
}

// Элементы уже существуют: favorable.js подключён после HTML.
var favTabElement = favEl("tab-favorable");
if (favTabElement) favTabElement.addEventListener("click", setFavorableMode);
var favTargetButton = favEl("fav-set-target");
if (favTargetButton) favTargetButton.addEventListener("click", enableFavTargetSelection);
var favLaunchButton = favEl("fav-set-launch");
if (favLaunchButton) favLaunchButton.addEventListener("click", enableFavLaunchSelection);
var favCalculateButton = favEl("calculate-favorable");
if (favCalculateButton) favCalculateButton.addEventListener("click", calculateFavorable);
