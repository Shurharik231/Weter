let map = null;

let startMarker = null;
let detectionMarker = null;

let directEndMarker = null;
let backLaunchMarker = null;

let directRouteLine = null;
let backRouteLine = null;

let directPointsLayer = null;
let backPointsLayer = null;

let selectionMode = null;

let directResult = null;
let backResult = null;

let activeMode = "direct";

function requireElement(id) {
    const element = document.getElementById(id);

    if (!element) {
        throw new Error(`Не найден HTML-элемент #${id}`);
    }

    return element;
}

function getElement(id) {
    return document.getElementById(id);
}

document.addEventListener("DOMContentLoaded", () => {
    try {
        initializeMap();
        initializeDateTimes();
        initializeTabs();
        initializeControls();
        initializeInitialMarkers();
        setActiveMode("direct");
    } catch (error) {
        console.error("Ошибка инициализации:", error);

        const status = getElement("status");

        if (status) {
            status.textContent = error.message;
            status.classList.add("error");
        }
    }
});

function initializeMap() {
    const mapElement = requireElement("map");

    map = L.map(mapElement, {
        zoomControl: true
    }).setView(
        [44.67, 34.41],
        7
    );

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors"
        }
    ).addTo(map);

    map.on("click", handleMapClick);
}

function toDateTimeLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");

    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function initializeDateTimes() {
    const now = new Date();

    const startTime = getElement("start-time");
    const backTime = getElement("back-time");

    if (startTime) {
        startTime.value = toDateTimeLocal(now);
    }

    if (backTime) {
        backTime.value = toDateTimeLocal(now);
    }
}

function initializeInitialMarkers() {
    const startLat = parseFloat(
        getElement("start-lat").value
    );

    const startLon = parseFloat(
        getElement("start-lon").value
    );

    if (validCoordinates(startLat, startLon)) {
        setStartMarker(
            startLat,
            startLon,
            false
        );
    }
}

function initializeTabs() {
    const directTab = requireElement("tab-direct");
    const backTab = requireElement("tab-back");

    directTab.addEventListener(
        "click",
        () => setActiveMode("direct")
    );

    backTab.addEventListener(
        "click",
        () => setActiveMode("back")
    );
}

function setActiveMode(mode) {
    activeMode =
        mode === "back"
            ? "back"
            : "direct";

    const directTab = getElement("tab-direct");
    const backTab = getElement("tab-back");
    const directPanel = getElement("direct-panel");
    const backPanel = getElement("back-panel");
    const mapMode = getElement("map-mode");

    if (directTab) {
        directTab.classList.toggle(
            "active",
            activeMode === "direct"
        );
    }

    if (backTab) {
        backTab.classList.toggle(
            "active",
            activeMode === "back"
        );
    }

    if (directPanel) {
        directPanel.classList.toggle(
            "hidden",
            activeMode !== "direct"
        );
    }

    if (backPanel) {
        backPanel.classList.toggle(
            "hidden",
            activeMode !== "back"
        );
    }

    if (mapMode) {
        mapMode.textContent =
            activeMode === "direct"
                ? "Прямая траектория"
                : "Обратная траектория";
    }

    selectionMode = null;

    updateActiveMapPoint();
}

function updateActiveMapPoint() {
    if (!map) {
        return;
    }

    if (activeMode === "direct") {
        if (startMarker) {
            startMarker.setZIndexOffset(1000);
            startMarker.setOpacity(1);
        }

        if (detectionMarker) {
            detectionMarker.setZIndexOffset(0);
            detectionMarker.setOpacity(0.35);
        }

        return;
    }

    if (activeMode === "back") {
        if (detectionMarker) {
            detectionMarker.setZIndexOffset(1000);
            detectionMarker.setOpacity(1);
        }

        if (startMarker) {
            startMarker.setZIndexOffset(0);
            startMarker.setOpacity(0.35);
        }
    }
}

function initializeControls() {
    const myLocation = getElement("my-location");

    if (myLocation) {
        myLocation.addEventListener(
            "click",
            useMyLocation
        );
    }

    const setStart = getElement("set-start");

    if (setStart) {
        setStart.addEventListener(
            "click",
            setStartFromInputs
        );
    }

    const calculateDirectButton =
        getElement("calculate-direct");

    if (calculateDirectButton) {
        calculateDirectButton.addEventListener(
            "click",
            calculateDirect
        );
    }

    const calculateBackButton =
        getElement("calculate-back");

    if (calculateBackButton) {
        calculateBackButton.addEventListener(
            "click",
            calculateBack
        );
    }

    const backMapPoint =
        getElement("back-map-point");

    if (backMapPoint) {
        backMapPoint.addEventListener(
            "click",
            enableDetectionSelection
        );
    }
}

function handleMapClick(event) {
    const lat = event.latlng.lat;
    const lon = event.latlng.lng;

    // ==========================================
    // БЛАГОПРИЯТНЫЕ УСЛОВИЯ
    // ==========================================
    if (favMode === "target") {
        if (favTargetLat) {
            favTargetLat.value = lat.toFixed(6);
        }

        if (favTargetLon) {
            favTargetLon.value = lon.toFixed(6);
        }

        updateFavTargetMarker(lat, lon);

        favMode = null;

        setStatus(
            `Цель установлена: ${lat.toFixed(5)}, ${lon.toFixed(5)}`
        );

        return;
    }

    if (favMode === "launch") {
        if (favLaunchLat) {
            favLaunchLat.value = lat.toFixed(6);
        }

        if (favLaunchLon) {
            favLaunchLon.value = lon.toFixed(6);
        }

        updateFavLaunchMarker(lat, lon);

        favMode = null;

        setStatus(
            `Центр запуска установлен: ${lat.toFixed(5)}, ${lon.toFixed(5)}`
        );

        return;
    }

    // ==========================================
    // ОБРАТНАЯ ТРАЕКТОРИЯ — выбор точки
    // ==========================================
    if (selectionMode === "back") {
        setDetectionMarker(
            lat,
            lon,
            true
        );

        selectionMode = null;

        setStatus(
            "Точка обнаружения выбрана."
        );

        return;
    }

    // ==========================================
    // ПРЯМАЯ ТРАЕКТОРИЯ
    // ==========================================
    if (activeMode === "direct") {
        setStartMarker(
            lat,
            lon,
            true
        );

        setStatus(
            "Точка старта установлена."
        );

        return;
    }

    // ==========================================
    // ОБРАТНАЯ ТРАЕКТОРИЯ
    // ==========================================
    if (activeMode === "back") {
        setDetectionMarker(
            lat,
            lon,
            true
        );

        setStatus(
            "Точка обнаружения установлена."
        );
    }
}


function setStartMarker(
    lat,
    lon,
    centerMap = false
) {
    if (!validCoordinates(lat, lon)) {
        setStatus(
            "Неверные координаты точки старта.",
            true
        );

        return;
    }

    if (startMarker) {
        startMarker.setLatLng([
            lat,
            lon
        ]);
    } else {
        startMarker = L.marker(
            [lat, lon],
            {
                draggable: true,
                zIndexOffset: 1000
            }
        ).addTo(map);

        startMarker.bindPopup(
            "Точка старта"
        );

        startMarker.on(
            "dragend",
            () => {
                const position =
                    startMarker.getLatLng();

                const latInput =
                    getElement("start-lat");

                const lonInput =
                    getElement("start-lon");

                if (latInput) {
                    latInput.value =
                        position.lat.toFixed(6);
                }

                if (lonInput) {
                    lonInput.value =
                        position.lng.toFixed(6);
                }
            }
        );
    }

    const latInput =
        getElement("start-lat");

    const lonInput =
        getElement("start-lon");

    if (latInput) {
        latInput.value =
            Number(lat).toFixed(6);
    }

    if (lonInput) {
        lonInput.value =
            Number(lon).toFixed(6);
    }

    if (centerMap) {
        map.setView(
            [lat, lon],
            Math.max(
                map.getZoom(),
                9
            )
        );
    }

    updateActiveMapPoint();
}

function setDetectionMarker(
    lat,
    lon,
    centerMap = false
) {
    if (!validCoordinates(lat, lon)) {
        setStatus(
            "Неверные координаты точки обнаружения.",
            true
        );

        return;
    }

    if (detectionMarker) {
        detectionMarker.setLatLng([
            lat,
            lon
        ]);
    } else {
        detectionMarker = L.marker(
            [lat, lon],
            {
                draggable: true,
                zIndexOffset: 1000
            }
        ).addTo(map);

        detectionMarker.bindPopup(
            "Точка обнаружения"
        );

        detectionMarker.on(
            "dragend",
            () => {
                const position =
                    detectionMarker.getLatLng();

                const latInput =
                    getElement("back-lat");

                const lonInput =
                    getElement("back-lon");

                if (latInput) {
                    latInput.value =
                        position.lat.toFixed(6);
                }

                if (lonInput) {
                    lonInput.value =
                        position.lng.toFixed(6);
                }
            }
        );
    }

    const latInput =
        getElement("back-lat");

    const lonInput =
        getElement("back-lon");

    if (latInput) {
        latInput.value =
            Number(lat).toFixed(6);
    }

    if (lonInput) {
        lonInput.value =
            Number(lon).toFixed(6);
    }

    if (centerMap) {
        map.setView(
            [lat, lon],
            Math.max(
                map.getZoom(),
                9
            )
        );
    }

    updateActiveMapPoint();
}

function enableDetectionSelection() {
    setActiveMode("back");

    selectionMode = "back";

    setStatus(
        "Кликните по карте, чтобы выбрать точку обнаружения."
    );
}

function useMyLocation() {
    if (!navigator.geolocation) {
        setStatus(
            "Браузер не поддерживает геолокацию.",
            true
        );

        return;
    }

    setStatus(
        "Получаем местоположение..."
    );

    navigator.geolocation.getCurrentPosition(
        position => {
            const lat =
                position.coords.latitude;

            const lon =
                position.coords.longitude;

            setStartMarker(
                lat,
                lon,
                true
            );

            setStatus(
                "Местоположение установлено как точка старта."
            );
        },
        error => {
            let message =
                "Не удалось получить геолокацию.";

            if (error && error.message) {
                message +=
                    " " +
                    error.message;
            }

            setStatus(
                message,
                true
            );
        },
        {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 60000
        }
    );
}

function setStartFromInputs() {
    const lat =
        parseFloat(
            getElement("start-lat").value
        );

    const lon =
        parseFloat(
            getElement("start-lon").value
        );

    if (!validCoordinates(lat, lon)) {
        setStatus(
            "Неверные координаты точки старта.",
            true
        );

        return;
    }

    setStartMarker(
        lat,
        lon,
        true
    );

    setStatus(
        "Точка старта установлена."
    );
}

async function calculateDirect() {
    setActiveMode("direct");

    selectionMode = null;

    clearDirectResultFromMap();

    const lat =
        parseFloat(
            getElement("start-lat").value
        );

    const lon =
        parseFloat(
            getElement("start-lon").value
        );

    if (!validCoordinates(lat, lon)) {
        setStatus(
            "Проверьте широту и долготу точки старта.",
            true
        );

        return;
    }

    const startTime =
        getElement("start-time").value;

    const startAltitude =
        parseFloat(
            getElement("start-altitude").value
        );

    const ascentRate =
        parseFloat(
            getElement("ascent-rate").value
        );

    const maxAltitude =
        parseFloat(
            getElement("max-altitude").value
        );

    const duration =
        parseFloat(
            getElement("duration").value
        );

    if (!startTime) {
        setStatus(
            "Укажите время старта.",
            true
        );

        return;
    }

    if (
        !Number.isFinite(startAltitude) ||
        !Number.isFinite(ascentRate) ||
        !Number.isFinite(maxAltitude) ||
        !Number.isFinite(duration)
    ) {
        setStatus(
            "Проверьте параметры прямой траектории.",
            true
        );

        return;
    }

    if (startAltitude > maxAltitude) {
        setStatus(
            "Высота старта не может быть выше максимальной.",
            true
        );

        return;
    }

    if (ascentRate < 0) {
        setStatus(
            "Скорость набора не может быть отрицательной.",
            true
        );

        return;
    }

    setStartMarker(
        lat,
        lon,
        false
    );

    setStatus(
        "Получаем прогноз ветра и рассчитываем прямую траекторию..."
    );

    try {
        const response = await fetch(
            "/api/trajectory",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    start: {
                        lat: lat,
                        lon: lon
                    },
                    start_time:
                        new Date(
                            startTime
                        ).toISOString(),
                    start_altitude:
                        startAltitude,
                    ascent_rate:
                        ascentRate,
                    max_altitude:
                        maxAltitude,
                    duration_hours:
                        duration,
                    step_minutes: 10
                })
            }
        );

        const data =
            await parseResponse(
                response
            );

        directResult = data;

        const points =
            extractTrajectoryPoints(
                data
            );

        if (!points.length) {
            throw new Error(
                "Сервер вернул результат без точек траектории."
            );
        }

        drawDirectTrajectory(
            data,
            points
        );

        showDirectResult(
            data,
            points
        );

        setStatus(
            `Прямая траектория рассчитана: ${points.length} точек.`
        );
    } catch (error) {
        console.error(
            "Ошибка прямой траектории:",
            error
        );

        setStatus(
            error.message ||
            "Ошибка расчёта прямой траектории.",
            true
        );
    }
}

async function calculateBack() {
    setActiveMode("back");

    selectionMode = null;

    clearBackResultFromMap();

    const lat =
        parseFloat(
            getElement("back-lat").value
        );

    const lon =
        parseFloat(
            getElement("back-lon").value
        );

    if (!validCoordinates(lat, lon)) {
        setStatus(
            "Проверьте широту и долготу точки обнаружения.",
            true
        );

        return;
    }

    const detectionTime =
        getElement("back-time").value;

    const altitude =
        parseFloat(
            getElement("back-altitude").value
        );

    if (!detectionTime) {
        setStatus(
            "Укажите время обнаружения.",
            true
        );

        return;
    }

    if (!Number.isFinite(altitude) || altitude < 0) {
        setStatus(
            "Проверьте высоту обнаружения.",
            true
        );

        return;
    }

    setDetectionMarker(
        lat,
        lon,
        false
    );

    setStatus(
        "Загружаем данные ERA5 и рассчитываем обратную траекторию..."
    );

    try {
        const response = await fetch(
            "/api/backtrajectory",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    detection: {
                        lat: lat,
                        lon: lon
                    },
                    detection_time:
                        new Date(
                            detectionTime
                        ).toISOString(),
                    altitude: altitude
                })
            }
        );

        const data =
            await parseResponse(
                response
            );

        backResult = data;

        const points =
            extractBackTrajectoryPoints(
                data
            );

        if (!points.length) {
            throw new Error(
                "Сервер вернул результат без точек обратной траектории."
            );
        }

        drawBackTrajectory(
            data,
            points
        );

        showBackResult(
            data,
            points
        );

        setStatus(
            `Обратная траектория рассчитана: ${points.length} точек.`
        );
    } catch (error) {
        console.error(
            "Ошибка обратной траектории:",
            error
        );

        setStatus(
            error.message ||
            "Ошибка расчёта обратной траектории.",
            true
        );
    }
}

async function parseResponse(response) {
    let data = null;

    try {
        data =
            await response.json();
    } catch (error) {
        throw new Error(
            "Сервер вернул некорректный JSON."
        );
    }

    if (!response.ok) {
        let message =
            `Ошибка сервера: HTTP ${response.status}`;

        if (
            data &&
            typeof data.detail === "string"
        ) {
            message =
                data.detail;
        } else if (
            data &&
            data.detail
        ) {
            message =
                JSON.stringify(
                    data.detail
                );
        }

        throw new Error(message);
    }

    return data;
}

function extractTrajectoryPoints(data) {
    if (!data) {
        return [];
    }

    if (Array.isArray(data.trajectory)) {
        return normalizePoints(
            data.trajectory
        );
    }

    if (Array.isArray(data.points)) {
        return normalizePoints(
            data.points
        );
    }

    if (Array.isArray(data.path)) {
        return normalizePoints(
            data.path
        );
    }

    if (Array.isArray(data)) {
        return normalizePoints(data);
    }

    return [];
}

function extractBackTrajectoryPoints(data) {
    if (!data) {
        return [];
    }

    // Сначала ищем плоский список точек (то, что мы специально добавили)
    if (data.result && Array.isArray(data.result.trajectory) && data.result.trajectory.length > 0) {
        return normalizePoints(data.result.trajectory);
    }

    if (data.result && Array.isArray(data.result.points) && data.result.points.length > 0) {
        return normalizePoints(data.result.points);
    }

    // Если плоского списка нет — пробуем взять первую траекторию из ансамбля
    if (
        data.result &&
        Array.isArray(data.result.trajectories) &&
        data.result.trajectories.length > 0 &&
        Array.isArray(data.result.trajectories[0])
    ) {
        return normalizePoints(data.result.trajectories[0]);
    }

    // Старые варианты на всякий случай
    if (Array.isArray(data.points)) {
        return normalizePoints(data.points);
    }

    if (Array.isArray(data.trajectory)) {
        return normalizePoints(data.trajectory);
    }

    if (Array.isArray(data.path)) {
        return normalizePoints(data.path);
    }

    if (Array.isArray(data)) {
        return normalizePoints(data);
    }

    return [];

    if (
        data.result &&
        Array.isArray(
            data.result.trajectories
        )
    ) {
        return normalizePoints(
            data.result.trajectories
        );
    }

    if (
        data.result &&
        Array.isArray(
            data.result.points
        )
    ) {
        return normalizePoints(
            data.result.points
        );
    }

    if (
        data.result &&
        Array.isArray(
            data.result.trajectory
        )
    ) {
        return normalizePoints(
            data.result.trajectory
        );
    }

    if (Array.isArray(data.points)) {
        return normalizePoints(
            data.points
        );
    }

    if (Array.isArray(data.trajectory)) {
        return normalizePoints(
            data.trajectory
        );
    }

    if (Array.isArray(data.path)) {
        return normalizePoints(
            data.path
        );
    }

    if (Array.isArray(data)) {
        return normalizePoints(data);
    }

    return [];
}

function normalizePoints(source) {
    if (!Array.isArray(source)) {
        return [];
    }

    const result = [];

    for (const rawPoint of source) {
        if (!rawPoint) {
            continue;
        }

        const lat =
            Number(
                rawPoint.lat ??
                rawPoint.latitude
            );

        const lon =
            Number(
                rawPoint.lon ??
                rawPoint.lng ??
                rawPoint.longitude
            );

        if (!validCoordinates(lat, lon)) {
            continue;
        }

        result.push({
            lat: lat,
            lon: lon,
            altitude:
                toNumberOrNull(
                    rawPoint.altitude ??
                    rawPoint.alt ??
                    rawPoint.height ??
                    rawPoint.altitude_m
                ),
            time:
                rawPoint.time ??
                rawPoint.datetime ??
                rawPoint.timestamp ??
                null,
            wind_speed:
                toNumberOrNull(
                    rawPoint.wind_speed ??
                    rawPoint.windSpeed ??
                    rawPoint.wind_speed_mps
                ),
            wind_direction:
                toNumberOrNull(
                    rawPoint.wind_direction ??
                    rawPoint.windDirection
                )
        });
    }

    return result;
}

function drawDirectTrajectory(
    data,
    points
) {
    removeDirectRoute();

    if (!points.length) {
        return;
    }

    const latLngs =
        points.map(
            point => [
                point.lat,
                point.lon
            ]
        );

    directRouteLine =
        L.polyline(
            latLngs,
            {
                weight: 5,
                opacity: 0.9
            }
        ).addTo(map);

    const first =
        points[0];

    setStartMarker(
        first.lat,
        first.lon,
        false
    );

    const last =
        points[
            points.length - 1
        ];

    directEndMarker =
        L.circleMarker(
            [
                last.lat,
                last.lon
            ],
            {
                radius: 7,
                weight: 2
            }
        ).addTo(map);

    directEndMarker.bindPopup(
        "Конечная точка"
    );

    directPointsLayer =
        L.layerGroup().addTo(map);

    addTrajectoryPointMarkers(
        directPointsLayer,
        points
    );

    updateActiveMapPoint();

    fitRoute(latLngs);
}

function drawBackTrajectory(
    data,
    points
) {
    removeBackRoute();

    if (!points.length) {
        return;
    }

    const latLngs =
        points.map(
            point => [
                point.lat,
                point.lon
            ]
        );

    backRouteLine =
        L.polyline(
            latLngs,
            {
                weight: 5,
                opacity: 0.9,
                dashArray: "10 7"
            }
        ).addTo(map);

    const detection =
        data.detection ||
        (
            data.result &&
            data.result.detection
        ) ||
        {
            lat:
                parseFloat(
                    getElement("back-lat").value
                ),
            lon:
                parseFloat(
                    getElement("back-lon").value
                )
        };

    if (
        detection &&
        validCoordinates(
            Number(detection.lat),
            Number(detection.lon)
        )
    ) {
        setDetectionMarker(
            Number(detection.lat),
            Number(detection.lon),
            false
        );
    }

    const result =
        data.result || data;

    const launch =
        result.launch_estimate ||
        result.estimated_launch ||
        data.launch_estimate ||
        data.estimated_launch ||
        points[0];

    if (
        launch &&
        validCoordinates(
            Number(
                launch.lat ??
                launch.latitude
            ),
            Number(
                launch.lon ??
                launch.lng ??
                launch.longitude
            )
        )
    ) {
        const launchLat =
            Number(
                launch.lat ??
                launch.latitude
            );

        const launchLon =
            Number(
                launch.lon ??
                launch.lng ??
                launch.longitude
            );

        backLaunchMarker =
            L.circleMarker(
                [
                    launchLat,
                    launchLon
                ],
                {
                    radius: 8,
                    weight: 2
                }
            ).addTo(map);

        backLaunchMarker.bindPopup(
            "Предполагаемая точка запуска"
        );
    }

    backPointsLayer =
        L.layerGroup().addTo(map);

    addTrajectoryPointMarkers(
        backPointsLayer,
        points
    );

    updateActiveMapPoint();

    fitRoute(latLngs);
}

function addTrajectoryPointMarkers(
    layer,
    points
) {
    const interval =
        Math.max(
            1,
            Math.floor(
                points.length / 30
            )
        );

    points.forEach(
        (
            point,
            index
        ) => {
            if (
                index % interval !== 0 &&
                index !==
                    points.length - 1
            ) {
                return;
            }

            const marker =
                L.circleMarker(
                    [
                        point.lat,
                        point.lon
                    ],
                    {
                        radius: 3,
                        weight: 1
                    }
                );

            const timeText =
                formatTime(
                    point.time
                );

            const altitudeText =
                point.altitude !== null
                    ? `${formatNumber(point.altitude)} м`
                    : "—";

            marker.bindTooltip(
                `${timeText}<br>Высота: ${altitudeText}`,
                {
                    direction: "top"
                }
            );

            marker.addTo(layer);
        }
    );
}

function showDirectResult(
    data,
    points
) {
    const result =
        getElement("results");

    const content =
        getElement("result-content");

    if (!result || !content) {
        return;
    }

    result.classList.remove(
        "hidden"
    );

    const start =
        data.start ||
        points[0] ||
        null;

    const end =
        data.end ||
        points[
            points.length - 1
        ] ||
        null;

    const startTime =
        start
            ? (
                start.time ??
                points[0]?.time
            )
            : null;

    const endTime =
        end
            ? (
                end.time ??
                points[
                    points.length - 1
                ]?.time
            )
            : null;

    const distance =
        firstNumber(
            data.distance_km,
            data.distance,
            calculateRouteDistance(points)
        );

    const maxAltitude =
        firstNumber(
            data.max_altitude,
            end?.altitude,
            calculateMaxAltitude(points)
        );

    const averageWind =
        firstNumber(
            data.average_wind_speed,
            calculateAverageWind(points)
        );

    const maxWind =
        firstNumber(
            data.max_wind_speed,
            calculateMaxWind(points)
        );

    const direction =
        firstNumber(
            data.prevailing_direction,
            data.wind_direction
        );

    content.innerHTML = `
        <div class="result-row">
            <span>Точек</span>
            <strong>${points.length}</strong>
        </div>

        <div class="result-row">
            <span>Начало</span>
            <strong>${formatTime(startTime)}</strong>
        </div>

        <div class="result-row">
            <span>Конец</span>
            <strong>${formatTime(endTime)}</strong>
        </div>

        <div class="result-row">
            <span>Конечная координата</span>
            <strong>
                ${
                    end
                        ? formatCoordinate(end.lat) +
                          ", " +
                          formatCoordinate(end.lon)
                        : "—"
                }
            </strong>
        </div>

        <div class="result-row">
            <span>Расстояние</span>
            <strong>${formatNumberOrDash(distance)} км</strong>
        </div>

        <div class="result-row">
            <span>Макс. высота</span>
            <strong>${formatNumberOrDash(maxAltitude)} м</strong>
        </div>

        <div class="result-row">
            <span>Средний ветер</span>
            <strong>${formatNumberOrDash(averageWind)} м/с</strong>
        </div>

        <div class="result-row">
            <span>Макс. ветер</span>
            <strong>${formatNumberOrDash(maxWind)} м/с</strong>
        </div>

        <div class="result-row">
            <span>Преобладающее направление</span>
            <strong>
                ${
                    direction !== null
                        ? formatNumber(direction) + "°"
                        : "—"
                }
            </strong>
        </div>
    `;
}

function showBackResult(
    data,
    points
) {
    const result =
        getElement("results");

    const content =
        getElement("result-content");

    if (!result || !content) {
        return;
    }

    result.classList.remove(
        "hidden"
    );

    const resultData =
        data.result || data;

    const launch =
        resultData.launch_estimate ||
        resultData.estimated_launch ||
        data.launch_estimate ||
        data.estimated_launch ||
        points[0] ||
        null;

    const distance =
        firstNumber(
            resultData.distance_km,
            resultData.distance,
            data.distance_km,
            data.distance,
            calculateRouteDistance(points)
        );

    const averageWind =
        firstNumber(
            resultData.average_wind_speed,
            data.average_wind_speed,
            calculateAverageWind(points)
        );

    const maxWind =
        firstNumber(
            resultData.max_wind_speed,
            data.max_wind_speed,
            calculateMaxWind(points)
        );

    const direction =
        firstNumber(
            resultData.prevailing_direction,
            resultData.wind_direction,
            data.prevailing_direction,
            data.wind_direction
        );

    const duration =
        firstNumber(
            resultData.duration_hours,
            data.duration_hours
        );

    const validLaunch =
        launch &&
        validCoordinates(
            Number(
                launch.lat ??
                launch.latitude
            ),
            Number(
                launch.lon ??
                launch.lng ??
                launch.longitude
            )
        )
            ? launch
            : null;

    const launchLat =
        validLaunch
            ? Number(
                validLaunch.lat ??
                validLaunch.latitude
            )
            : null;

    const launchLon =
        validLaunch
            ? Number(
                validLaunch.lon ??
                validLaunch.lng ??
                validLaunch.longitude
            )
            : null;

    const launchAltitude =
        validLaunch
            ? firstNumber(
                validLaunch.altitude,
                validLaunch.altitude_m,
                validLaunch.alt,
                validLaunch.height
            )
            : null;

    const launchTime =
        validLaunch
            ? (
                validLaunch.time ??
                validLaunch.datetime ??
                validLaunch.timestamp
            )
            : null;

    content.innerHTML = `
        <div class="result-highlight">
            <div>Предполагаемая точка запуска</div>

            <strong>
                ${
                    validLaunch
                        ? formatCoordinate(launchLat) +
                          ", " +
                          formatCoordinate(launchLon)
                        : "—"
                }
            </strong>
        </div>

        <div class="result-row">
            <span>Время предполагаемого запуска</span>
            <strong>
                ${formatTime(launchTime)}
            </strong>
        </div>

        <div class="result-row">
            <span>Высота</span>
            <strong>
                ${
                    launchAltitude !== null
                        ? formatNumber(launchAltitude) + " м"
                        : "—"
                }
            </strong>
        </div>

        <div class="result-row">
            <span>Точек траектории</span>
            <strong>${points.length}</strong>
        </div>

        <div class="result-row">
            <span>Время назад</span>
            <strong>
                ${
                    duration !== null
                        ? formatNumber(duration) + " ч"
                        : "—"
                }
            </strong>
        </div>

        <div class="result-row">
            <span>Расстояние</span>
            <strong>
                ${formatNumberOrDash(distance)} км
            </strong>
        </div>

        <div class="result-row">
            <span>Средняя скорость ветра</span>
            <strong>
                ${formatNumberOrDash(averageWind)} м/с
            </strong>
        </div>

        <div class="result-row">
            <span>Максимальная скорость ветра</span>
            <strong>
                ${formatNumberOrDash(maxWind)} м/с
            </strong>
        </div>

        <div class="result-row">
            <span>Преобладающее направление</span>
            <strong>
                ${
                    direction !== null
                        ? formatNumber(direction) + "°"
                        : "—"
                }
            </strong>
        </div>
    `;
}

function showResults() {
    const results =
        getElement("results");

    if (results) {
        results.classList.remove(
            "hidden"
        );
    }
}

function hideResults() {
    const results =
        getElement("results");

    if (results) {
        results.classList.add(
            "hidden"
        );
    }
}

function removeDirectRoute() {
    if (
        directRouteLine &&
        map.hasLayer(directRouteLine)
    ) {
        map.removeLayer(
            directRouteLine
        );
    }

    directRouteLine = null;

    if (
        directPointsLayer &&
        map.hasLayer(directPointsLayer)
    ) {
        map.removeLayer(
            directPointsLayer
        );
    }

    directPointsLayer = null;

    if (
        directEndMarker &&
        map.hasLayer(directEndMarker)
    ) {
        map.removeLayer(
            directEndMarker
        );
    }

    directEndMarker = null;
}

function removeBackRoute() {
    if (
        backRouteLine &&
        map.hasLayer(backRouteLine)
    ) {
        map.removeLayer(
            backRouteLine
        );
    }

    backRouteLine = null;

    if (
        backPointsLayer &&
        map.hasLayer(backPointsLayer)
    ) {
        map.removeLayer(
            backPointsLayer
        );
    }

    backPointsLayer = null;

    if (
        backLaunchMarker &&
        map.hasLayer(backLaunchMarker)
    ) {
        map.removeLayer(
            backLaunchMarker
        );
    }

    backLaunchMarker = null;
}

function clearDirectResultFromMap() {
    removeDirectRoute();
}

function clearBackResultFromMap() {
    removeBackRoute();
}

function clearAllRoutes() {
    removeDirectRoute();
    removeBackRoute();
}

function fitRoute(latLngs) {
    if (
        !Array.isArray(latLngs) ||
        !latLngs.length
    ) {
        return;
    }

    if (latLngs.length === 1) {
        map.setView(
            latLngs[0],
            Math.max(
                map.getZoom(),
                9
            )
        );

        return;
    }

    const bounds =
        L.latLngBounds(
            latLngs
        );

    if (bounds.isValid()) {
        map.fitBounds(
            bounds,
            {
                padding: [
                    50,
                    50
                ]
            }
        );
    }
}

function setStatus(
    text,
    error = false
) {
    const element =
        getElement("status");

    if (!element) {
        return;
    }

    element.textContent =
        text || "";

    element.classList.toggle(
        "error",
        Boolean(error)
    );
}

function validCoordinates(
    lat,
    lon
) {
    return (
        Number.isFinite(Number(lat)) &&
        Number.isFinite(Number(lon)) &&
        Number(lat) >= -90 &&
        Number(lat) <= 90 &&
        Number(lon) >= -180 &&
        Number(lon) <= 180
    );
}

function toNumberOrNull(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const number =
        Number(value);

    return Number.isFinite(number)
        ? number
        : null;
}

function firstNumber(...values) {
    for (const value of values) {
        const number =
            toNumberOrNull(value);

        if (number !== null) {
            return number;
        }
    }

    return null;
}

function formatCoordinate(value) {
    const number =
        Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toFixed(5);
}

function formatNumber(value) {
    const number =
        Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toFixed(2);
}

function formatNumberOrDash(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toFixed(2);
}

function formatTime(value) {
    if (!value) {
        return "—";
    }

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return "—";
    }

    return date.toLocaleString(
        "ru-RU",
        {
            dateStyle: "short",
            timeStyle: "short"
        }
    );
}

function calculateRouteDistance(points) {
    if (
        !Array.isArray(points) ||
        points.length < 2
    ) {
        return 0;
    }

    let totalMeters = 0;

    for (
        let index = 1;
        index < points.length;
        index++
    ) {
        const a =
            points[index - 1];

        const b =
            points[index];

        const first =
            L.latLng(
                a.lat,
                a.lon
            );

        const second =
            L.latLng(
                b.lat,
                b.lon
            );

        totalMeters +=
            first.distanceTo(
                second
            );
    }

    return totalMeters / 1000;
}

function calculateMaxAltitude(points) {
    let maximum = null;

    for (const point of points) {
        if (point.altitude === null) {
            continue;
        }

        if (
            maximum === null ||
            point.altitude > maximum
        ) {
            maximum =
                point.altitude;
        }
    }

    return maximum;
}

function calculateAverageWind(points) {
    const values =
        points
            .map(
                point =>
                    point.wind_speed
            )
            .filter(
                value =>
                    value !== null &&
                    Number.isFinite(value)
            );

    if (!values.length) {
        return null;
    }

    const sum =
        values.reduce(
            (
                total,
                value
            ) =>
                total + value,
            0
        );

    return sum / values.length;
}

function calculateMaxWind(points) {
    const values =
        points
            .map(
                point =>
                    point.wind_speed
            )
            .filter(
                value =>
                    value !== null &&
                    Number.isFinite(value)
            );

    if (!values.length) {
        return null;
    }

    return Math.max(
        ...values
    );
}

const tabFavorable = document.getElementById('tab-favorable');
const favorablePanel = document.getElementById('favorable-panel');

function setStatus(text, isError = false) {
    const el = document.getElementById('status');

    if (!el) return;

    el.textContent = text;
    el.style.color = isError ? '#e74c3c' : '';
}
