// Третий режим: поиск возможных окон запуска.
// Загружается перед app.js и работает с уже существующим Leaflet map.
var favMode = null;
var favTargetLat = document.getElementById("fav-target-lat");
var favTargetLon = document.getElementById("fav-target-lon");
var favLaunchLat = document.getElementById("fav-launch-lat");
var favLaunchLon = document.getElementById("fav-launch-lon");
var favTargetMarker = null;
var favLaunchMarker = null;
var favTargetCircle = null;
var favLaunchCircle = null;
var favTrajectoryLayer = null;
var favResultData = null;

function favEl(id) { return document.getElementById(id); }

function favMapReady() {
    return typeof map !== "undefined" && map && typeof L !== "undefined";
}

function updateFavTargetMarker(lat, lon) {
    if (!favMapReady()) return;
    if (favTargetMarker) {
        favTargetMarker.setLatLng([lat, lon]);
    } else {
        favTargetMarker = L.marker([lat, lon], { draggable: true }).addTo(map);
        favTargetMarker.bindPopup("Целевая точка");
        favTargetMarker.on("dragend", function () {
            var p = favTargetMarker.getLatLng();
            favEl("fav-target-lat").value = p.lat.toFixed(6);
            favEl("fav-target-lon").value = p.lng.toFixed(6);
        });
    }
    if (favTargetCircle) favTargetCircle.setLatLng([lat, lon]);
    else favTargetCircle = L.circle([lat, lon], { radius: Number(favEl("fav-max-dist")?.value) || 5000 }).addTo(map);
}

function updateFavLaunchMarker(lat, lon) {
    if (!favMapReady()) return;
    if (favLaunchMarker) {
        favLaunchMarker.setLatLng([lat, lon]);
    } else {
        favLaunchMarker = L.marker([lat, lon], { draggable: true }).addTo(map);
        favLaunchMarker.bindPopup("Центр области запуска");
        favLaunchMarker.on("dragend", function () {
            var p = favLaunchMarker.getLatLng();
            favEl("fav-launch-lat").value = p.lat.toFixed(6);
            favEl("fav-launch-lon").value = p.lng.toFixed(6);
            updateFavLaunchCircle();
        });
    }
    updateFavLaunchCircle();
}

function updateFavLaunchCircle() {
    if (!favMapReady() || !favLaunchMarker) return;
    var radius = Number(favEl("fav-radius")?.value) || 1000;
    var p = favLaunchMarker.getLatLng();
    if (favLaunchCircle) {
        favLaunchCircle.setLatLng(p);
        favLaunchCircle.setRadius(radius);
    } else {
        favLaunchCircle = L.circle(p, { radius: radius }).addTo(map);
    }
}

function clearFavorableMap() {
    if (!favMapReady()) return;
    if (favTrajectoryLayer) {
        map.removeLayer(favTrajectoryLayer);
        favTrajectoryLayer = null;
    }
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

    if (favMapReady()) {
        updateFavTargetMarker(Number(favTargetLat?.value), Number(favTargetLon?.value));
        updateFavLaunchMarker(Number(favLaunchLat?.value), Number(favLaunchLon?.value));
    }
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

function setFavSearchDefaults() {
    var start = favEl("fav-search-start");
    var end = favEl("fav-search-end");
    if (!start || !end) return;
    var now = new Date();
    var later = new Date(now.getTime() + 72 * 3600000);
    if (!start.value) start.value = toDateTimeLocalFav(now);
    if (!end.value) end.value = toDateTimeLocalFav(later);
}

function toDateTimeLocalFav(date) {
    var pad = function (v) { return String(v).padStart(2, "0"); };
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
}

function renderFavorableMap(data) {
    if (!favMapReady()) return;
    clearFavorableMap();

    var group = L.layerGroup().addTo(map);
    favTrajectoryLayer = group;
    var bounds = [];
    var windows = data.windows || [];

    windows.forEach(function (windowItem, wi) {
        (windowItem.best_candidates || []).forEach(function (candidate, ci) {
            var points = candidate.trajectory && candidate.trajectory.points || [];
            if (points.length < 2) return;
            var latlngs = points.map(function (p) { return [p.lat, p.lon]; });
            latlngs.forEach(function (p) { bounds.push(p); });
            var isBest = wi === 0 && ci === 0;
            var line = L.polyline(latlngs, {
                weight: isBest ? 5 : 2,
                opacity: isBest ? 0.95 : 0.35,
                dashArray: isBest ? null : "6 8"
            }).addTo(group);
            line.bindPopup(
                "Окно " + (wi + 1) + "<br>Запуск: " + new Date(candidate.launch_time).toLocaleString("ru-RU") +
                "<br>Мин. расстояние: " + Math.round(candidate.min_distance_to_target_m) + " м" +
                "<br>В цели: " + (Number(candidate.time_in_target_s || 0) / 60).toFixed(1) + " мин"
            );
        });
    });

    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 11 });
}

function formatMeters(value) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n >= 1000 ? (n / 1000).toFixed(2) + " км" : Math.round(n) + " м";
}

function renderFavorableResults(data) {
    var results = favEl("results");
    var content = favEl("result-content");
    if (results) results.classList.remove("hidden");
    var windows = data.windows || [];

    if (!windows.length) {
        if (content) content.innerHTML = "<div class='result-card'>Подходящих окон не найдено.</div>";
        return;
    }

    if (!content) return;
    content.innerHTML = windows.map(function (w, i) {
        var best = (w.best_candidates || [])[0];
        if (!best) return "";
        var closest = best.closest_point || {};
        var success = best.ensemble_success_rate;
        var weather = best.weather || {};
        return '<div class="result-card">' +
            '<strong>Окно #' + (i + 1) + '</strong>' +
            '<div><b>Период:</b> ' + new Date(w.window_start).toLocaleString("ru-RU") + ' — ' + new Date(w.window_end).toLocaleString("ru-RU") + '</div>' +
            '<div><b>Рекомендуемый запуск:</b> ' + new Date(w.recommended_time).toLocaleString("ru-RU") + '</div>' +
            '<div><b>Точка:</b> ' + Number(best.launch_point.lat).toFixed(5) + ', ' + Number(best.launch_point.lon).toFixed(5) + '</div>' +
            '<div><b>Минимум до цели:</b> ' + formatMeters(best.min_distance_to_target_m) + '</div>' +
            '<div><b>В целевой области:</b> ' + (Number(best.time_in_target_s || 0) / 60).toFixed(1) + ' мин</div>' +
            '<div><b>Максимальное сближение:</b> ' + (closest.time ? new Date(closest.time).toLocaleString("ru-RU") : "—") + (closest.altitude != null ? ' на высоте ' + Math.round(closest.altitude) + ' м' : '') + '</div>' +
            (success != null ? '<div><b>Успешность ансамбля:</b> ' + (Number(success) * 100).toFixed(0) + '%</div>' : '') +
            (weather.surface_wind_speed_mps != null ? '<div><b>Приземный ветер:</b> ' + Number(weather.surface_wind_speed_mps).toFixed(1) + ' м/с</div>' : '') +
            '</div>';
    }).join("");
}

async function calculateFavorable() {
    setFavorableMode();
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
    clearFavorableMap();
    setFavorableStatus("Получаем прогноз ветра и ищем варианты запуска...");

    try {
        var payload = {
            target: { lat: targetLat, lon: targetLon },
            launch_center: { lat: launchLat, lon: launchLon },
            search_start: new Date(start).toISOString(),
            search_end: new Date(end).toISOString(),
            launch_radius_m: Number(favEl("fav-radius")?.value) || 1000,
            radius_tolerance_m: 100,
            time_step_hours: 1,
            window_half_width_hours: 3,
            max_acceptable_distance_m: Number(favEl("fav-max-dist")?.value) || 5000,
            ascent_rate: Number(favEl("fav-ascent")?.value) || 5,
            max_altitude: Number(favEl("fav-max-alt")?.value) || 9000,
            duration_hours: Number(favEl("fav-duration")?.value) || 5,
            step_minutes: 2,
            start_altitude: 0,
            points_per_circle: 7
        };

        var response = await fetch("/api/favorable", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        var data = await response.json();
        if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));
        favResultData = data;
        renderFavorableResults(data);
        renderFavorableMap(data);

        if (!data.windows || !data.windows.length) {
            setFavorableStatus("Расчёт завершён: подходящих окон не найдено.");
            return;
        }
        setFavorableStatus("Готово: найдено окон — " + data.windows.length + ". Лучшие траектории показаны на карте.");
    } catch (error) {
        console.error("Ошибка благоприятных условий:", error);
        setFavorableStatus(error.message || "Ошибка расчёта.", true);
    } finally {
        if (button) button.disabled = false;
    }
}

// Инициализация выполняется после HTML: favorable.js подключён перед app.js.
setFavSearchDefaults();
var favTabElement = favEl("tab-favorable");
if (favTabElement) favTabElement.addEventListener("click", setFavorableMode);
var favTargetButton = favEl("fav-set-target");
if (favTargetButton) favTargetButton.addEventListener("click", enableFavTargetSelection);
var favLaunchButton = favEl("fav-set-launch");
if (favLaunchButton) favLaunchButton.addEventListener("click", enableFavLaunchSelection);
var favCalculateButton = favEl("calculate-favorable");
if (favCalculateButton) favCalculateButton.addEventListener("click", calculateFavorable);
var favRadiusInput = favEl("fav-radius");
if (favRadiusInput) favRadiusInput.addEventListener("change", updateFavLaunchCircle);
var favMaxDistanceInput = favEl("fav-max-dist");
if (favMaxDistanceInput) favMaxDistanceInput.addEventListener("change", function () {
    if (favTargetCircle) favTargetCircle.setRadius(Number(favMaxDistanceInput.value) || 5000);
});
