from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import asin, cos, degrees, radians, sin, sqrt, atan2
import os
import random
import time
from typing import Any, Callable

from models import FlightParameters, StartPoint, Trajectory, TrajectoryPoint
from trajectory import calculate_trajectory
from weather import interpolate_wind

EARTH_RADIUS_M = 6_371_000.0
ProgressCallback = Callable[[dict], None]
_WORKER_FORECAST: dict[str, Any] | None = None

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _seconds_between(a: datetime, b: datetime) -> float: return (_utc(a) - _utc(b)).total_seconds()

@dataclass(frozen=True)
class GeoPoint: lat: float; lon: float
@dataclass
class Candidate:
    launch_time: datetime; launch_point: GeoPoint; trajectory: Trajectory; min_distance_m: float; closest_point: TrajectoryPoint; time_in_target_s: float; surface_wind_mps: float; shear_s_inv: float; hazard_hit: bool; restricted_hit: bool; ensemble_success_rate: float = 0.0; ensemble_median_distance_m: float = 0.0; ensemble_p90_distance_m: float = 0.0; score: float = float("inf")
@dataclass
class FavorableWindow:
    window_start: datetime; window_end: datetime; recommended_time: datetime; candidates: list[Candidate] = field(default_factory=list)

def _distance_m(a: GeoPoint, b: GeoPoint) -> float:
    p1,p2=radians(a.lat),radians(b.lat);dp=radians(b.lat-a.lat);dl=radians(b.lon-a.lon);h=sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2
    return 2*EARTH_RADIUS_M*asin(sqrt(max(0.0,min(1.0,h))))
def _offset(center: GeoPoint,east_m: float,north_m: float)->GeoPoint:
    return GeoPoint(center.lat+north_m/111320.0,center.lon+east_m/(111320.0*max(0.15,cos(radians(center.lat)))))
def generate_launch_points(center: GeoPoint,radius_m: float,rings: int=2,points_per_ring: int=12)->list[GeoPoint]:
    result=[center];rings=max(1,int(rings));points_per_ring=max(8,int(points_per_ring))
    for ring in range(1,rings+1):
        radius=radius_m*ring/rings;count=max(8,points_per_ring*ring)
        for i in range(count):
            angle=2*3.141592653589793*i/count;result.append(_offset(center,radius*sin(angle),radius*cos(angle)))
    return result

def _point_in_polygon(point: GeoPoint,polygon:list[GeoPoint])->bool:
    if len(polygon)<3:return False
    inside=False;j=len(polygon)-1
    for i,p in enumerate(polygon):
        q=polygon[j]
        if (p.lon>point.lon)!=(q.lon>point.lon):
            x=(q.lat-p.lat)*(point.lon-p.lon)/(q.lon-p.lon)+p.lat
            if point.lat<x:inside=not inside
        j=i
    return inside

def _segments_intersect(a:GeoPoint,b:GeoPoint,c:GeoPoint,d:GeoPoint)->bool:
    def orient(p,q,r):return (q.lon-p.lon)*(r.lat-p.lat)-(q.lat-p.lat)*(r.lon-p.lon)
    def on_segment(p,q,r):return min(p.lon,r.lon)-1e-12<=q.lon<=max(p.lon,r.lon)+1e-12 and min(p.lat,r.lat)-1e-12<=q.lat<=max(p.lat,r.lat)+1e-12
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    if o1==0 and on_segment(a,c,b):return True
    if o2==0 and on_segment(a,d,b):return True
    if o3==0 and on_segment(c,a,d):return True
    if o4==0 and on_segment(c,b,d):return True
    return ((o1>0)!=(o2>0)) and ((o3>0)!=(o4>0))

def _trajectory_hits_polygon(points:list[TrajectoryPoint],polygon:list[GeoPoint])->bool:
    if len(polygon)<3:return False
    for a,b in zip(points,points[1:]):
        pa,pb=GeoPoint(a.lat,a.lon),GeoPoint(b.lat,b.lon)
        if _point_in_polygon(pa,polygon) or _point_in_polygon(pb,polygon):return True
        for c,d in zip(polygon,polygon[1:]+polygon[:1]):
            if _segments_intersect(pa,pb,c,d):return True
    return False

def _target_membership(point:GeoPoint,target:GeoPoint|None,radius_m:float,polygon:list[GeoPoint]|None)->bool:
    if polygon and len(polygon)>=3:return _point_in_polygon(point,polygon)
    return target is not None and _distance_m(point,target)<=radius_m

def _segment_circle_hit(a:GeoPoint,b:GeoPoint,center:GeoPoint,radius_m:float)->tuple[bool,float]:
    lat0=radians(center.lat);sx=EARTH_RADIUS_M*cos(lat0);sy=EARTH_RADIUS_M
    ax=(radians(a.lon)-radians(center.lon))*sx;ay=(radians(a.lat)-radians(center.lat))*sy;bx=(radians(b.lon)-radians(center.lon))*sx;by=(radians(b.lat)-radians(center.lat))*sy;dx,dy=bx-ax,by-ay;aa=dx*dx+dy*dy
    if aa<1e-12:return (ax*ax+ay*ay<=radius_m*radius_m,1.0 if ax*ax+ay*ay<=radius_m*radius_m else 0.0)
    t=max(0.0,min(1.0,-(ax*dx+ay*dy)/aa));px,py=ax+t*dx,ay+t*dy;dist2=px*px+py*py
    if dist2>radius_m*radius_m:return False,0.0
    half=sqrt(max(0.0,radius_m*radius_m-dist2)/aa);lo=max(0.0,t-half);hi=min(1.0,t+half);return True,max(0.0,hi-lo)

def _segment_target_hit(a:TrajectoryPoint,b:TrajectoryPoint,target:GeoPoint|None,radius_m:float,polygon:list[GeoPoint]|None)->tuple[bool,float]:
    pa,pb=GeoPoint(a.lat,a.lon),GeoPoint(b.lat,b.lon)
    if polygon and len(polygon)>=3:
        if _point_in_polygon(pa,polygon) or _point_in_polygon(pb,polygon):return True,0.5
        if any(_segments_intersect(pa,pb,c,d) for c,d in zip(polygon,polygon[1:]+polygon[:1])):return True,0.5
        return False,0.0
    return _segment_circle_hit(pa,pb,target,radius_m) if target is not None else (False,0.0)

def _trajectory_quality(points:list[TrajectoryPoint],target:GeoPoint|None,radius_m:float,target_polygon:list[GeoPoint]|None=None)->tuple[float,TrajectoryPoint,float,bool]:
    if not points:raise ValueError("Траектория не содержит точек")
    best_d=float("inf");best=points[0];inside=0.0;hit=False
    if target is not None:
        for p in points:
            d=_distance_m(GeoPoint(p.lat,p.lon),target)
            if d<best_d:best_d,best=d,p
    for a,b in zip(points,points[1:]):
        dt=max(0.0,_seconds_between(b.time,a.time));segment_hit,fraction=_segment_target_hit(a,b,target,radius_m,target_polygon);ia=_target_membership(GeoPoint(a.lat,a.lon),target,radius_m,target_polygon);ib=_target_membership(GeoPoint(b.lat,b.lon),target,radius_m,target_polygon)
        if ia and ib:inside+=dt;hit=True
        elif segment_hit:inside+=dt*max(0.0,min(1.0,fraction));hit=True
    if target_polygon and len(target_polygon)>=3:hit=hit or _trajectory_hits_polygon(points,target_polygon)
    return best_d,best,inside,hit

def _wind_vector(forecast:dict[str,Any],lat:float,lon:float,altitude:float,when:datetime)->tuple[float,float]:
    speed,direction=interpolate_wind(forecast,lat,lon,altitude,_utc(when));towards=radians((direction+180)%360);return speed*sin(towards),speed*cos(towards)
def _surface_and_shear(forecast:dict[str,Any],point:GeoPoint,when:datetime,top_m:float)->tuple[float,float]:
    when=_utc(when);surface=interpolate_wind(forecast,point.lat,point.lon,10.0,when)[0];top_u,top_v=_wind_vector(forecast,point.lat,point.lon,max(100.0,top_m),when);low_u,low_v=_wind_vector(forecast,point.lat,point.lon,10.0,when);return surface,sqrt((top_u-low_u)**2+(top_v-low_v)**2)/max(1.0,top_m-10.0)
def _weather_hazard(forecast:dict[str,Any],points:list[TrajectoryPoint],precipitation_limit_mm:float)->bool:
    cells=forecast.get("cells",[])
    if not cells:return False
    for p in points:
        cell=min(cells,key=lambda c:(float(c.get("latitude",0))-p.lat)**2+(float(c.get("longitude",0))-p.lon)**2);hourly=cell.get("hourly",{});times=hourly.get("time",[])
        if not times:continue
        p_time=_utc(p.time);parsed=[_utc(datetime.fromisoformat(t.replace("Z","+00:00"))) for t in times];idx=min(range(len(parsed)),key=lambda i:abs(_seconds_between(parsed[i],p_time)));codes=hourly.get("weather_code",[]);precip=hourly.get("precipitation",[]);code=codes[idx] if idx<len(codes) else None;rain=precip[idx] if idx<len(precip) and precip[idx] is not None else 0.0
        if code is not None and int(code) in {95,96,99}:return True
        if float(rain)>precipitation_limit_mm:return True
    return False

def _perturb_forecast(forecast:dict[str,Any],seed:int,wind_sigma_mps:float)->dict[str,Any]:
    rng=random.Random(seed)
    result=dict(forecast)
    result["cells"]=[]
    for source_cell in forecast.get("cells",[]):
        cell=dict(source_cell)
        source_hourly=source_cell.get("hourly",{})
        hourly=dict(source_hourly)
        cell["hourly"]=hourly
        result["cells"].append(cell)
        common_e=common_n=series_e=series_n=0.0
        for level in [k[len("wind_speed_"):] for k in source_hourly if k.startswith("wind_speed_")]:
            source_speeds=source_hourly.get(f"wind_speed_{level}");source_directions=source_hourly.get(f"wind_direction_{level}")
            if not source_speeds or not source_directions:continue
            speeds=list(source_speeds);directions=list(source_directions)
            hourly[f"wind_speed_{level}"]=speeds;hourly[f"wind_direction_{level}"]=directions
            for i,(s,d) in enumerate(zip(speeds,directions)):
                if s is None or d is None:continue
                sigma=wind_sigma_mps*(1.0+0.35*sqrt(max(0.0,i)/24.0));common_e=0.82*common_e+rng.gauss(0,sigma*0.30);common_n=0.82*common_n+rng.gauss(0,sigma*0.30);series_e=0.88*series_e+rng.gauss(0,sigma*0.55);series_n=0.88*series_n+rng.gauss(0,sigma*0.55);towards=radians((float(d)+180)%360);u=float(s)*sin(towards)+common_e+series_e;v=float(s)*cos(towards)+common_n+series_n;speed=sqrt(u*u+v*v);directions[i]=(degrees(atan2(u,v))+180)%360 if speed>1e-9 else 0.0;speeds[i]=speed
    return result

def _ensemble_member(args):
    params,base_forecast,target,target_polygon,radius_m,member,wind_sigma_mps,restricted,hazards=args
    forecast=base_forecast if member==0 else _perturb_forecast(base_forecast,member*1009,wind_sigma_mps)
    try:trajectory=calculate_trajectory(params,forecast)
    except Exception:return None
    d,_,_,hit=_trajectory_quality(trajectory.points,target,radius_m,target_polygon);restricted_hit=any(_trajectory_hits_polygon(trajectory.points,poly) for poly in restricted);hazard_hit=any(_trajectory_hits_polygon(trajectory.points,poly) for poly in hazards)
    return d,bool(hit and not restricted_hit and not hazard_hit)

def _init_worker(forecast:dict[str,Any]):
    global _WORKER_FORECAST
    _WORKER_FORECAST=forecast

def _screen_candidate_worker(args):
    launch_time,launch,params,target,target_polygon,target_radius_m,surface_wind_limit_mps,shear_limit_s_inv,precipitation_limit_mm,restricted_zones,hazard_zones=args
    return _screen_candidate((launch_time,launch,params,_WORKER_FORECAST,target,target_polygon,target_radius_m,surface_wind_limit_mps,shear_limit_s_inv,precipitation_limit_mm,restricted_zones,hazard_zones))

def _ensemble_member_worker(args):
    params,target,target_polygon,radius_m,member,wind_sigma_mps,restricted,hazards=args
    return _ensemble_member((params,_WORKER_FORECAST,target,target_polygon,radius_m,member,wind_sigma_mps,restricted,hazards))

def _screen_candidate(args):
    launch_time,launch,params,forecast,target,target_polygon,target_radius_m,surface_wind_limit_mps,shear_limit_s_inv,precipitation_limit_mm,restricted_zones,hazard_zones=args
    try:trajectory=calculate_trajectory(params,forecast)
    except Exception:return None
    d,closest,inside,hit=_trajectory_quality(trajectory.points,target,target_radius_m,target_polygon);surface,shear=_surface_and_shear(forecast,launch,launch_time,params.max_altitude);restricted_hit=any(_trajectory_hits_polygon(trajectory.points,z) for z in restricted_zones);hazard_hit=_weather_hazard(forecast,trajectory.points,precipitation_limit_mm) or any(_trajectory_hits_polygon(trajectory.points,z) for z in hazard_zones)
    if hit and surface<=surface_wind_limit_mps and shear<=shear_limit_s_inv and not restricted_hit and not hazard_hit:
        pre_score=d/max(100.0,target_radius_m)-min(inside/3600.0,2.0)*0.15+(surface/max(0.1,surface_wind_limit_mps))*0.05+(shear/max(1e-9,shear_limit_s_inv))*0.05
        return Candidate(launch_time,launch,trajectory,d,closest,inside,surface,shear,hazard_hit,restricted_hit,score=pre_score)
    return None

def _ensemble_metrics_batch(selected:list[Candidate],forecast:dict[str,Any],target:GeoPoint|None,target_polygon:list[GeoPoint]|None,target_radius_m:float,ensemble_members:int,ensemble_wind_sigma_mps:float,restricted_zones:list[list[GeoPoint]],hazard_zones:list[list[GeoPoint]],start_altitude:float,ascent_rate:float,max_altitude:float,duration_hours:float,step_minutes:int,progress_callback:ProgressCallback|None,started:float)->None:
    member_count=max(1,ensemble_members);total=len(selected)*member_count;done=0;results=[[] for _ in selected]
    tasks=[]
    for idx,c in enumerate(selected):
        params=FlightParameters(StartPoint(c.launch_point.lat,c.launch_point.lon),_utc(c.launch_time),start_altitude,ascent_rate,max_altitude,duration_hours,step_minutes)
        for member in range(member_count):tasks.append((idx,(params,target,target_polygon,target_radius_m,member,ensemble_wind_sigma_mps,restricted_zones,hazard_zones)))
    workers=min(total,max(1,os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=workers,initializer=_init_worker,initargs=(forecast,)) as executor:
        future_to_idx={executor.submit(_ensemble_member_worker,args):idx for idx,args in tasks}
        for future in as_completed(future_to_idx):
            idx=future_to_idx[future];result=future.result()
            if result is not None:results[idx].append(result)
            done+=1
            if progress_callback:
                elapsed=time.monotonic()-started;eta=elapsed/done*(total-done) if done else None;progress_callback({"stage":"ensemble","processed":done,"total":total,"percent":100*done/max(1,total),"elapsed_s":elapsed,"eta_s":eta,"message":f"Ансамблевый расчёт: кандидат {idx+1}/{len(selected)}"})
    for c,values in zip(selected,results):
        if not values:
            c.ensemble_success_rate,c.ensemble_median_distance_m,c.ensemble_p90_distance_m=0.0,float("inf"),float("inf")
            continue
        distances=sorted(v[0] for v in values);successes=sum(1 for _,ok in values if ok);n=len(distances)
        c.ensemble_success_rate=successes/n;c.ensemble_median_distance_m=distances[n//2];c.ensemble_p90_distance_m=distances[min(n-1,int(0.90*(n-1)))]
        c.score=c.ensemble_p90_distance_m/max(100.0,target_radius_m)-c.ensemble_success_rate*2.0+c.min_distance_m/max(100.0,target_radius_m)

def find_favorable_windows(*,target:GeoPoint|None,target_polygon:list[GeoPoint]|None=None,launch_center:GeoPoint,forecast:dict[str,Any],search_start:datetime,search_end:datetime,launch_radius_m:float,target_radius_m:float,time_step_hours:float,duration_hours:float,step_minutes:float,ascent_rate:float,max_altitude:float,start_altitude:float,launch_points_rings:int,launch_points_per_ring:int,surface_wind_limit_mps:float,shear_limit_s_inv:float,ensemble_members:int,ensemble_wind_sigma_mps:float,precipitation_limit_mm:float,restricted_zones:list[list[GeoPoint]]|None=None,hazard_zones:list[list[GeoPoint]]|None=None,progress_callback:ProgressCallback|None=None)->list[FavorableWindow]:
    search_start,search_end=_utc(search_start),_utc(search_end);restricted_zones=restricted_zones or [];hazard_zones=hazard_zones or []
    if target is None and not target_polygon:raise ValueError("Нужно задать target или target_polygon")
    points=generate_launch_points(launch_center,launch_radius_m,launch_points_rings,launch_points_per_ring);candidates=[];t=search_start;step=timedelta(hours=time_step_hours);times=[]
    while t<=search_end:times.append(t);t+=step
    total_screen=len(points)*len(times);started=time.monotonic()
    if progress_callback:progress_callback({"stage":"screen","processed":0,"total":total_screen,"percent":0,"elapsed_s":0,"eta_s":None,"message":"Параллельный первичный отбор точек и времени","force":True})
    screen_tasks=[];calc_step=int(max(1,round(step_minutes)))
    for t in times:
        launch_time=_utc(t)
        for launch in points:
            params=FlightParameters(StartPoint(launch.lat,launch.lon),launch_time,start_altitude,ascent_rate,max_altitude,duration_hours,calc_step)
            screen_tasks.append((launch_time,launch,params,target,target_polygon,target_radius_m,surface_wind_limit_mps,shear_limit_s_inv,precipitation_limit_mm,restricted_zones,hazard_zones))
    workers=min(total_screen,max(1,os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=workers,initializer=_init_worker,initargs=(forecast,)) as executor:
        future_to_task={executor.submit(_screen_candidate_worker,args):i for i,args in enumerate(screen_tasks)}
        for processed,future in enumerate(as_completed(future_to_task),1):
            candidate=future.result()
            if candidate is not None:candidates.append(candidate)
            if progress_callback:
                elapsed=time.monotonic()-started;eta=elapsed/processed*(total_screen-processed) if processed else None;progress_callback({"stage":"screen","processed":processed,"total":total_screen,"percent":100*processed/max(1,total_screen),"elapsed_s":elapsed,"eta_s":eta,"message":"Параллельный первичный отбор"})
    if not candidates:
        if progress_callback:progress_callback({"stage":"done","processed":1,"total":1,"percent":100,"elapsed_s":time.monotonic()-started,"eta_s":0,"message":"Подходящих кандидатов не найдено","force":True})
        return []
    candidates.sort(key=lambda c:c.score);target_count=min(len(candidates),max(24,int(len(candidates)*0.20)));selected=candidates[:target_count];best_per_time={}
    for c in candidates:best_per_time.setdefault(c.launch_time,c)
    selected_ids={id(c) for c in selected}
    for c in best_per_time.values():
        if len(selected)>=min(len(candidates),target_count+len(best_per_time)):break
        if id(c) not in selected_ids:selected.append(c);selected_ids.add(id(c))
    selected.sort(key=lambda c:c.score);total_ensemble=len(selected)*max(1,ensemble_members)
    if progress_callback:progress_callback({"stage":"ensemble","processed":0,"total":total_ensemble,"percent":0,"elapsed_s":time.monotonic()-started,"eta_s":None,"message":f"Точный ансамблевый расчёт: {len(selected)} перспективных кандидатов","force":True})
    _ensemble_metrics_batch(selected,forecast,target,target_polygon,target_radius_m,ensemble_members,ensemble_wind_sigma_mps,restricted_zones,hazard_zones,start_altitude,ascent_rate,max_altitude,duration_hours,calc_step,progress_callback,started)
    final=sorted(selected,key=lambda c:c.score);windows=[]
    for c in final:
        if not windows or _seconds_between(c.launch_time,windows[-1].window_end)>3600:windows.append(FavorableWindow(c.launch_time,c.launch_time,c.launch_time,[c]))
        else:windows[-1].window_end=max(windows[-1].window_end,c.launch_time);windows[-1].candidates.append(c);windows[-1].recommended_time=min(windows[-1].candidates,key=lambda x:x.score).launch_time
    if progress_callback:progress_callback({"stage":"done","processed":1,"total":1,"percent":100,"elapsed_s":time.monotonic()-started,"eta_s":0,"message":"Расчёт завершён","force":True})
    return windows
