from __future__ import annotations

import bisect
import time
from datetime import datetime, timezone
from math import cos, radians, sin, sqrt, atan2, degrees
from typing import Any

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL_SECONDS = 900
CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PRESSURE_LEVELS = [(1000,"1000hPa"),(975,"975hPa"),(950,"950hPa"),(925,"925hPa"),(900,"900hPa"),(850,"850hPa"),(800,"800hPa"),(700,"700hPa"),(600,"600hPa"),(550,"550hPa"),(500,"500hPa"),(450,"450hPa"),(400,"400hPa"),(350,"350hPa"),(300,"300hPa")]

class WeatherError(RuntimeError):
    pass

def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _variables() -> list[str]:
    result = []
    for _, level in PRESSURE_LEVELS:
        result += [f"wind_speed_{level}", f"wind_direction_{level}", f"geopotential_height_{level}"]
    result += ["precipitation", "weather_code"]
    return result

def _cache_key(latitudes, longitudes, start, end) -> str:
    return "|".join([",".join(f"{x:.3f}" for x in latitudes), ",".join(f"{x:.3f}" for x in longitudes), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")])

def build_grid(center_lat: float, center_lon: float, radius_km: float) -> tuple[list[float], list[float]]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(20.0, 111.0 * cos(radians(center_lat)))
    return ([center_lat + lat_delta*x for x in (-1,-0.5,0,0.5,1)], [center_lon + lon_delta*x for x in (-1,-0.5,0,0.5,1)])

def _make_coordinate_pairs(latitudes, longitudes):
    return [(lat, lon) for lat in latitudes for lon in longitudes]

async def fetch_grid(latitudes, longitudes, start: datetime, end: datetime) -> dict[str, Any]:
    start = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise WeatherError("Конец периода прогноза должен быть позже начала.")
    horizon_hours = (end - start).total_seconds() / 3600.0
    if horizon_hours > 16 * 24:
        raise WeatherError("Период расчёта превышает максимальный горизонт Weather Forecast API (16 суток).")
    key = _cache_key(latitudes, longitudes, start, end)
    cached = CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    coordinates = _make_coordinate_pairs(latitudes, longitudes)
    params = {
        "latitude": ",".join(f"{lat:.4f}" for lat,_ in coordinates),
        "longitude": ",".join(f"{lon:.4f}" for _,lon in coordinates),
        "hourly": ",".join(_variables()),
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
        "forecast_days": min(16, max(1, int((horizon_hours + 23.999) // 24))),
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
    if response.status_code != 200:
        raise WeatherError(f"Open-Meteo HTTP {response.status_code}: {response.text[:500]}")
    data = response.json()
    if isinstance(data, dict): data = [data]
    if not data: raise WeatherError("Open-Meteo вернул пустой ответ.")
    if any("hourly" not in cell for cell in data): raise WeatherError("В ответе Open-Meteo отсутствует hourly.")
    result = {"latitudes": latitudes, "longitudes": longitudes, "cells": data, "coordinates": coordinates}
    CACHE[key] = (time.monotonic(), result)
    if len(CACHE) > 8:
        CACHE.pop(min(CACHE, key=lambda k: CACHE[k][0]), None)
    return result

def _wind_to_uv(speed: float, direction_from: float) -> tuple[float,float]:
    direction_towards = radians((direction_from + 180.0) % 360.0)
    return sin(direction_towards)*speed, cos(direction_towards)*speed

def _uv_to_wind(east: float, north: float) -> tuple[float,float]:
    speed = sqrt(east*east + north*north)
    if speed < 1e-6: return 0.0, 0.0
    towards = (degrees(atan2(east,north)) + 360) % 360
    return speed, (towards + 180) % 360

def _time_indices(times: list[datetime], target: datetime):
    if target < times[0] or target > times[-1]:
        raise WeatherError(f"Время {target.isoformat()} выходит за границы загруженного прогноза {times[0].isoformat()} — {times[-1].isoformat()}.")
    if target == times[-1]:
        n=len(times)-1; return n,n,0.0
    i1=bisect.bisect_right(times,target); i0=i1-1
    total=(times[i1]-times[i0]).total_seconds()
    return i0,i1,0.0 if total<=0 else (target-times[i0]).total_seconds()/total

def _cell_wind(cell, altitude: float, target_time: datetime):
    hourly=cell["hourly"]; times=[_parse_time(t) for t in hourly["time"]]
    t0,t1,tf=_time_indices(times,target_time); vectors=[]
    for _,level in PRESSURE_LEVELS:
        try:
            s0=float(hourly[f"wind_speed_{level}"][t0]); s1=float(hourly[f"wind_speed_{level}"][t1])
            d0=float(hourly[f"wind_direction_{level}"][t0]); d1=float(hourly[f"wind_direction_{level}"][t1])
            h0=float(hourly[f"geopotential_height_{level}"][t0]); h1=float(hourly[f"geopotential_height_{level}"][t1])
        except (KeyError,TypeError,ValueError,IndexError): continue
        e0,n0=_wind_to_uv(s0,d0); e1,n1=_wind_to_uv(s1,d1)
        vectors.append((h0+(h1-h0)*tf,e0+(e1-e0)*tf,n0+(n1-n0)*tf))
    if not vectors: raise WeatherError("Для выбранного времени нет данных ветра.")
    vectors.sort(key=lambda x:x[0])
    if altitude <= vectors[0][0]: return _uv_to_wind(vectors[0][1],vectors[0][2])
    if altitude >= vectors[-1][0]: return _uv_to_wind(vectors[-1][1],vectors[-1][2])
    for (h0,e0,n0),(h1,e1,n1) in zip(vectors,vectors[1:]):
        if h0 <= altitude <= h1:
            f=0.0 if abs(h1-h0)<0.001 else (altitude-h0)/(h1-h0)
            return _uv_to_wind(e0+(e1-e0)*f,n0+(n1-n0)*f)
    return _uv_to_wind(vectors[-1][1],vectors[-1][2])

def _find_cell(forecast, lat, lon):
    return min(forecast["cells"], key=lambda c:(float(c["latitude"])-lat)**2+(float(c["longitude"])-lon)**2)

def _bilinear_wind(forecast, lat, lon, altitude, target_time):
    lats=sorted(forecast["latitudes"]); lons=sorted(forecast["longitudes"])
    if not (lats[0] <= lat <= lats[-1] and lons[0] <= lon <= lons[-1]):
        raise WeatherError("Траектория вышла за пределы загруженной метеосетки.")
    def surrounding(values,target):
        if target<=values[0]: return values[0],values[0],0.0
        if target>=values[-1]: return values[-1],values[-1],0.0
        i=bisect.bisect_right(values,target); a,b=values[i-1],values[i]
        return a,b,(target-a)/(b-a)
    lat0,lat1,fy=surrounding(lats,lat); lon0,lon1,fx=surrounding(lons,lon)
    cells=[_find_cell(forecast,a,b) for a,b in ((lat0,lon0),(lat0,lon1),(lat1,lon0),(lat1,lon1))]
    winds=[_cell_wind(c,altitude,target_time) for c in cells]
    vec=[_wind_to_uv(*w) for w in winds]
    e0=vec[0][0]+(vec[1][0]-vec[0][0])*fx; e1=vec[2][0]+(vec[3][0]-vec[2][0])*fx
    n0=vec[0][1]+(vec[1][1]-vec[0][1])*fx; n1=vec[2][1]+(vec[3][1]-vec[2][1])*fx
    return _uv_to_wind(e0+(e1-e0)*fy,n0+(n1-n0)*fy)

def interpolate_wind(forecast, lat, lon, altitude, when):
    return _bilinear_wind(forecast,lat,lon,altitude,when)

def wind_field(forecast, lat, lon, altitude, when, radius_km=150, count=9):
    return [{"lat":a,"lon":b,"speed":interpolate_wind(forecast,a,b,altitude,when)[0],"direction":interpolate_wind(forecast,a,b,altitude,when)[1]} for a in forecast["latitudes"] for b in forecast["longitudes"]]
