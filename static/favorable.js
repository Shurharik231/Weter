// Дополнительный модуль режима «Благоприятные условия».
// Глобальные переменные нужны потому, что основной app.js обрабатывает клик карты.
var favMode = null;
var favTargetLat = document.getElementById("fav-target-lat");
var favTargetLon = document.getElementById("fav-target-lon");
var favLaunchLat = document.getElementById("fav-launch-lat");
var favLaunchLon = document.getElementById("fav-launch-lon");
var favTargetMarker = null;
var favLaunchMarker = null;

function updateFavTargetMarker(lat, lon) {
    const m = typeof map !== "undefined" ? map : null;
    if (!m) return;
    if (favTargetMarker) {
        favTargetMarker.setLatLng([lat, lon]);
    } else {
        favTargetMarker = L.marker([lat, lon], { draggable: true }).addTo(m);
        favTargetMarker.bindPopup("Целевая точка");
    }
}

function updateFavLaunchMarker(lat, lon) {
    const m = typeof map !== "undefined" ? map : null;
    if (!m) return;
    if (favLaunchMarker) {
        favLaunchMarker.setLatLng([lat, lon]);
    } else {
        favLaunchMarker = L.marker([lat, lon], { draggable: true }).addTo(m);
        favLaunchMarker.bindPopup("Центр области запуска");
    }
}

function setFavorableMode() {
    const directTab = document.getElementById("tab-direct");
    const backTab = document.getElementById("tab-back");
    const favTab = document.getElementById("tab-favorable");
    const directPanel = document.getElementById("direct-panel");
    const backPanel = document.getElementById("back-panel");
    const favPanel = document.getElementById("favorable-panel");
    const label = document.getElementById("map-mode");

    directTab?.classList.remove("active");
    backTab?.classList.remove("active");
    favTab?.classList.add("active");
    directPanel?.classList.add("hidden");
    backPanel?.classList.add("hidden");
    favPanel?.classList.remove("hidden");
    if (label) label.textContent = "Благоприятные условия";
    favMode = null;
    if (typeof selectionMode !== "undefined") selectionMode = null;
}

function validFavCoordinates(lat, lon) {
    return Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)) &&
        Number(lat) >= -90 && Number(lat) <= 90 &&
        Number(lon) >= -180 && Number(lon) <= 180;
}

function setFavorableStatus(text, error = false) {
    const el = document.getElementById("status");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("error", error);
}

async function calculateFavorable() {
    const targetLat = Number(document.getElementById("fav-target-lat")?.value);
    const targetLon = Number(document.getElementById("fav-target-lon")?.value);
    const launchLat = Number(document.getElementById("fav-launch-lat")?.value);
    const launchLon = Number(document.getElementById("fav-launch-lon")?.value);

    if (!validFavCoordinates(targetLat, targetLon) || !validFavCoordinates(launchLat, launchLon)) {
        setFavorableStatus("Проверьте координаты цели и области запуска.", true);
        return;
    }

    const start = document.getElementById("fav-search-start")?.value;
    const end = document.getElementById("fav-search-end")?.value;
    if (!start || !end) {
        setFavorableStatus("Укажите начало и конец периода поиска.", true);
        return;
    }

    const button = document.getElementById("calculate-favorable");
    if (button) button.disabled = true;
    setFavorableStatus("Ищем благоприятные окна...");

    try {
        const payload = {
            target: { lat: targetLat, lon: targetLon },
            launch_center: { lat: launchLat, lon: launchLon },
            search_start: new Date(start).toISOString(),
            search_end: new Date(end).toISOString(),
            launch_radius_m: Number(document.getElementById("fav-radius")?.value) || 1000,
            radius_tolerance_m: 100,
            time_step_hours: 1,
            window_half_width_hours: 3,
            max_acceptable_distance_m: Number(document.getElementById("fav-max-dist")?.value) || 5000,
            ascent_rate: Number(document.getElementById("fav-ascent")?.value) || 5,
            max_altitude: Number(document.getElementById("fav-max-alt")?.value) || 9000,
            duration_hours: Number(document.getElementById("fav-duration")?.value) || 5,
            step_minutes: 2,
            start_altitude: 0,
            points_per_circle: 7
        };

        const response = await fetch("/api/favorable", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

        const results = document.getElementById("results");
        const content = document.getElementById("result-content");
        results?.classList.remove("hidden");

        if (!data.windows?.length) {
            if (content) content.innerHTML = "<div class='result-card'>Подходящих окон не найдено.</div>";
            setFavorableStatus("Расчёт завершён: подходящих окон не найдено.");
            return;
        }

        if (content) {
            content.innerHTML = data.windows.map((w, i) => `
                <div class="result-card">
                    <strong>Окно ${i + 1}: ${w.date || "—"}</strong>
                    <div>Период: ${new Date(w.window_start).toLocaleString("ru-RU")} — ${new Date(w.window_end).toLocaleString("ru-RU")}</div>
                    <div>Рекомендуемый запуск: ${new Date(w.recommended_time).toLocaleString("ru-RU")}</div>
                    <div>Кандидатов: ${w.best_candidates?.length || 0}</div>
                </div>`).join("");
        }

        const first = data.windows[0]?.best_candidates?.[0];
        const points = first?.trajectory?.points || [];
        if (typeof map !== "undefined" && points.length > 1) {
            const latLngs = points.map(p => [Number(p.lat), Number(p.lon)]).filter(p => validFavCoordinates(p[0], p[1]));
            if (latLngs.length > 1) {
                L.polyline(latLngs, { weight: 5, dashArray: "8 6" }).addTo(map);
                map.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
            }
        }
        setFavorableStatus(`Готово: найдено окон — ${data.windows.length}.`);
    } catch (error) {
        console.error("Ошибка благоприятных условий:", error);
        setFavorableStatus(error.message || "Ошибка расчёта.", true);
    } finally {
        if (button) button.disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tab-favorable")?.addEventListener("click", setFavorableMode);

    document.getElementById("fav-set-target")?.addEventListener("click", () => {
        setFavorableMode();
        favMode = "target";
        setFavorableStatus("Кликните по карте, чтобы установить целевую точку.");
    });

    document.getElementById("fav-set-launch")?.addEventListener("click", () => {
        setFavorableMode();
        favMode = "launch";
        setFavorableStatus("Кликните по карте, чтобы установить центр области запуска.");
    });

    document.getElementById("calculate-favorable")?.addEventListener("click", calculateFavorable);
});
