// Дополнительный модуль для режима «Благоприятные условия».
// Основной app.js оставляем без переписывания: он содержит основной frontend.
(function () {
    let favMode = null;
    let favTargetMarker = null;
    let favLaunchMarker = null;

    const $ = (id) => document.getElementById(id);

    function setFavStatus(text, error = false) {
        const el = $("status");
        if (!el) return;
        el.textContent = text || "";
        el.classList.toggle("error", Boolean(error));
    }

    function valid(lat, lon) {
        return Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)) &&
            Number(lat) >= -90 && Number(lat) <= 90 &&
            Number(lon) >= -180 && Number(lon) <= 180;
    }

    function updateMarker(marker, lat, lon, popupText) {
        if (marker) {
            marker.setLatLng([lat, lon]);
            return marker;
        }
        marker = L.marker([lat, lon], { draggable: true }).addTo(window.map || window.__weterMap);
        marker.bindPopup(popupText);
        return marker;
    }

    function setMapMode(mode) {
        const directTab = $("tab-direct");
        const backTab = $("tab-back");
        const favTab = $("tab-favorable");
        const directPanel = $("direct-panel");
        const backPanel = $("back-panel");
        const favPanel = $("favorable-panel");
        const modeLabel = $("map-mode");

        [directTab, backTab, favTab].forEach((el) => el && el.classList.remove("active"));
        if (mode === "direct") directTab?.classList.add("active");
        if (mode === "back") backTab?.classList.add("active");
        if (mode === "favorable") favTab?.classList.add("active");

        directPanel?.classList.toggle("hidden", mode !== "direct");
        backPanel?.classList.toggle("hidden", mode !== "back");
        favPanel?.classList.toggle("hidden", mode !== "favorable");
        if (modeLabel) modeLabel.textContent = mode === "favorable" ? "Благоприятные условия" : (mode === "back" ? "Обратная траектория" : "Прямая траектория");

        if (typeof activeMode !== "undefined") activeMode = mode === "back" ? "back" : "direct";
        if (typeof selectionMode !== "undefined") selectionMode = null;
    }

    function getMap() {
        if (typeof map !== "undefined" && map) return map;
        if (window.__weterMap) return window.__weterMap;
        return null;
    }

    function placeFavTarget(lat, lon) {
        $("fav-target-lat").value = Number(lat).toFixed(6);
        $("fav-target-lon").value = Number(lon).toFixed(6);
        const m = getMap();
        if (m) {
            if (favTargetMarker) favTargetMarker.setLatLng([lat, lon]);
            else favTargetMarker = L.marker([lat, lon], { draggable: true }).addTo(m).bindPopup("Целевая точка");
        }
    }

    function placeFavLaunch(lat, lon) {
        $("fav-launch-lat").value = Number(lat).toFixed(6);
        $("fav-launch-lon").value = Number(lon).toFixed(6);
        const m = getMap();
        if (m) {
            if (favLaunchMarker) favLaunchMarker.setLatLng([lat, lon]);
            else favLaunchMarker = L.marker([lat, lon], { draggable: true }).addTo(m).bindPopup("Центр области запуска");
        }
    }

    function drawWindow(windowData) {
        const m = getMap();
        const candidates = windowData?.best_candidates || [];
        if (!m || !candidates.length) return;
        const candidate = candidates[0];
        const trajectory = candidate.trajectory?.points || candidate.trajectory || [];
        const latLngs = trajectory.map(p => [Number(p.lat), Number(p.lon)]).filter(p => valid(p[0], p[1]));
        if (latLngs.length > 1) {
            L.polyline(latLngs, { weight: 5, dashArray: "8 6" }).addTo(m);
            m.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
        }
    }

    async function calculateFavorable() {
        const targetLat = Number($("fav-target-lat").value);
        const targetLon = Number($("fav-target-lon").value);
        const launchLat = Number($("fav-launch-lat").value);
        const launchLon = Number($("fav-launch-lon").value);
        if (!valid(targetLat, targetLon) || !valid(launchLat, launchLon)) {
            setFavStatus("Проверьте координаты цели и области запуска.", true);
            return;
        }

        const start = $("fav-search-start").value;
        const end = $("fav-search-end").value;
        if (!start || !end) {
            setFavStatus("Укажите начало и конец периода поиска.", true);
            return;
        }

        const button = $("calculate-favorable");
        if (button) button.disabled = true;
        setFavStatus("Ищем благоприятные окна и рассчитываем траектории...");

        try {
            const payload = {
                target: { lat: targetLat, lon: targetLon },
                launch_center: { lat: launchLat, lon: launchLon },
                search_start: new Date(start).toISOString(),
                search_end: new Date(end).toISOString(),
                launch_radius_m: Number($("fav-radius").value) || 1000,
                radius_tolerance_m: 100,
                time_step_hours: 1,
                window_half_width_hours: 3,
                max_acceptable_distance_m: Number($("fav-max-dist").value) || 5000,
                ascent_rate: Number($("fav-ascent").value) || 5,
                max_altitude: Number($("fav-max-alt").value) || 9000,
                duration_hours: Number($("fav-duration").value) || 5,
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

            const result = $("result-content");
            $("results")?.classList.remove("hidden");
            if (!data.windows?.length) {
                if (result) result.innerHTML = "<div class='result-card'>Подходящих окон не найдено.</div>";
                setFavStatus("Расчёт завершён: подходящих окон не найдено.");
                return;
            }

            if (result) {
                result.innerHTML = data.windows.map((w, i) => `
                    <div class="result-card">
                        <strong>Окно ${i + 1}: ${w.date || "—"}</strong>
                        <div>Период: ${new Date(w.window_start).toLocaleString("ru-RU")} — ${new Date(w.window_end).toLocaleString("ru-RU")}</div>
                        <div>Рекомендуемый запуск: ${new Date(w.recommended_time).toLocaleString("ru-RU")}</div>
                        <div>Кандидатов: ${w.best_candidates?.length || 0}</div>
                    </div>`).join("");
            }
            drawWindow(data.windows[0]);
            setFavStatus(`Готово: найдено окон — ${data.windows.length}.`);
        } catch (error) {
            console.error("Ошибка благоприятных условий:", error);
            setFavStatus(error.message || "Ошибка расчёта.", true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const favTab = $("tab-favorable");
        favTab?.addEventListener("click", () => setMapMode("favorable"));

        $("fav-set-target")?.addEventListener("click", () => {
            setMapMode("favorable");
            favMode = "target";
            setFavStatus("Кликните по карте, чтобы установить целевую точку.");
        });

        $("fav-set-launch")?.addEventListener("click", () => {
            setMapMode("favorable");
            favMode = "launch";
            setFavStatus("Кликните по карте, чтобы установить центр области запуска.");
        });

        $("calculate-favorable")?.addEventListener("click", calculateFavorable);

        const m = getMap();
        if (m) {
            m.on("click", (e) => {
                if (favMode === "target") {
                    placeFavTarget(e.latlng.lat, e.latlng.lng);
                    favMode = null;
                    setFavStatus("Целевая точка установлена.");
                } else if (favMode === "launch") {
                    placeFavLaunch(e.latlng.lat, e.latlng.lng);
                    favMode = null;
                    setFavStatus("Центр области запуска установлен.");
                }
            });
        }
    });
})();
