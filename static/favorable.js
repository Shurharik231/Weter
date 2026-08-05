// Третий режим: поиск возможных окон запуска + live progress.
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
var favPollTimer = null;

function favEl(id) { return document.getElementById(id); }
function favMapReady() { return typeof map !== "undefined" && map && typeof L !== "undefined"; }
function favIcon(type) {
    var colors = { target: "#dc2626", launch: "#16a34a", detect: "#7c3aed" };
    var color = colors[type] || "#2563eb";
    return L.divIcon({ className: "fav-map-marker", html: '<span style="--marker-color:' + color + '"></span>', iconSize: [24,24], iconAnchor: [12,12], popupAnchor: [0,-12] });
}
function updateFavTargetMarker(lat, lon) {
    if (!favMapReady() || !validFavCoordinates(lat, lon)) return;
    if (favTargetMarker) favTargetMarker.setLatLng([lat, lon]);
    else {
        favTargetMarker = L.marker([lat, lon], {draggable:true, icon:favIcon("target"), zIndexOffset:1200}).addTo(map);
        favTargetMarker.bindTooltip("Цель", {direction:"top", offset:[0,-8]});
        favTargetMarker.on("dragend", function(){ var p=favTargetMarker.getLatLng(); favEl("fav-target-lat").value=p.lat.toFixed(6); favEl("fav-target-lon").value=p.lng.toFixed(6); });
    }
    var radius=Number(favEl("fav-max-dist")?.value)||5000;
    if(favTargetCircle){favTargetCircle.setLatLng([lat,lon]);favTargetCircle.setRadius(radius);}
    else favTargetCircle=L.circle([lat,lon],{radius:radius,color:"#dc2626",fillColor:"#dc2626",fillOpacity:.08,weight:2,dashArray:"6 5"}).addTo(map);
}
function updateFavLaunchMarker(lat, lon) {
    if(!favMapReady() || !validFavCoordinates(lat,lon)) return;
    if(favLaunchMarker) favLaunchMarker.setLatLng([lat,lon]);
    else {
        favLaunchMarker=L.marker([lat,lon],{draggable:true,icon:favIcon("launch"),zIndexOffset:1100}).addTo(map);
        favLaunchMarker.bindTooltip("Область возможного запуска",{direction:"top",offset:[0,-8]});
        favLaunchMarker.on("dragend",function(){var p=favLaunchMarker.getLatLng();favEl("fav-launch-lat").value=p.lat.toFixed(6);favEl("fav-launch-lon").value=p.lng.toFixed(6);updateFavLaunchCircle();});
    }
    updateFavLaunchCircle();
}
function updateFavLaunchCircle(){
    if(!favMapReady()||!favLaunchMarker)return;
    var radius=Number(favEl("fav-radius")?.value)||1000,p=favLaunchMarker.getLatLng();
    if(favLaunchCircle){favLaunchCircle.setLatLng(p);favLaunchCircle.setRadius(radius);}
    else favLaunchCircle=L.circle(p,{radius:radius,color:"#16a34a",fillColor:"#16a34a",fillOpacity:.09,weight:2}).addTo(map);
}
function clearFavorableMap(){if(!favMapReady())return;if(favTrajectoryLayer){map.removeLayer(favTrajectoryLayer);favTrajectoryLayer=null;}}
function setFavorableMode(){
    var directTab=favEl("tab-direct"),backTab=favEl("tab-back"),favTab=favEl("tab-favorable"),directPanel=favEl("direct-panel"),backPanel=favEl("back-panel"),favPanel=favEl("favorable-panel"),mapMode=favEl("map-mode");
    if(directTab)directTab.classList.remove("active");if(backTab)backTab.classList.remove("active");if(favTab)favTab.classList.add("active");if(directPanel)directPanel.classList.add("hidden");if(backPanel)backPanel.classList.add("hidden");if(favPanel)favPanel.classList.remove("hidden");if(mapMode)mapMode.textContent="● Благоприятные условия";if(typeof activeMode!=="undefined")activeMode="favorable";if(typeof selectionMode!=="undefined")selectionMode=null;favMode=null;setFavSearchDefaults();
    if(favMapReady()){updateFavTargetMarker(Number(favTargetLat?.value),Number(favTargetLon?.value));updateFavLaunchMarker(Number(favLaunchLat?.value),Number(favLaunchLon?.value));}
}
function setFavorableStatus(text,error){var status=favEl("status");if(!status)return;status.textContent=text||"";status.classList.toggle("error",!!error);}
function enableFavTargetSelection(){setFavorableMode();favMode="target";setFavorableStatus("Кликните по карте, чтобы установить целевую точку.");}
function enableFavLaunchSelection(){setFavorableMode();favMode="launch";setFavorableStatus("Кликните по карте, чтобы установить центр области запуска.");}
function validFavCoordinates(lat,lon){return Number.isFinite(Number(lat))&&Number.isFinite(Number(lon))&&Number(lat)>=-90&&Number(lat)<=90&&Number(lon)>=-180&&Number(lon)<=180;}
function setFavSearchDefaults(){var start=favEl("fav-search-start"),end=favEl("fav-search-end");if(!start||!end)return;var now=new Date(),later=new Date(now.getTime()+72*3600000);if(!start.value)start.value=toDateTimeLocalFav(now);if(!end.value)end.value=toDateTimeLocalFav(later);}
function toDateTimeLocalFav(date){var pad=function(v){return String(v).padStart(2,"0")};return date.getFullYear()+"-"+pad(date.getMonth()+1)+"-"+pad(date.getDate())+"T"+pad(date.getHours())+":"+pad(date.getMinutes());}

function ensureFavProgress(){
    var p=favEl("favorable-progress");if(p)return p;
    p=document.createElement("section");p.id="favorable-progress";p.className="favorable-progress";p.hidden=true;
    p.innerHTML='<div class="favorable-progress-head"><strong id="fav-progress-title">Расчёт окон запуска</strong><span id="fav-progress-percent">0%</span></div><div class="favorable-progress-track"><div id="fav-progress-fill"></div></div><div class="favorable-progress-stage" id="fav-progress-stage">Подготовка…</div><div class="favorable-progress-stats"><span>Проверено <b id="fav-progress-count">0 / 0</b></span><span>Время <b id="fav-progress-elapsed">0 с</b></span><span>Осталось <b id="fav-progress-eta">—</b></span></div>';
    var anchor=favEl("results")||favEl("favorable-panel");if(anchor&&anchor.parentNode)anchor.parentNode.insertBefore(p,anchor);else document.body.appendChild(p);return p;
}
function formatFavTime(s){if(!Number.isFinite(Number(s))||Number(s)<0)return "—";s=Math.round(Number(s));if(s<60)return s+" с";return Math.floor(s/60)+" мин "+String(s%60).padStart(2,"0")+" с";}
function updateFavProgress(d){
    ensureFavProgress().hidden=false;var pct=Math.max(0,Math.min(100,Number(d.percent)||0));
    var fill=favEl("fav-progress-fill"),p=favEl("fav-progress-percent"),c=favEl("fav-progress-count"),stage=favEl("fav-progress-stage"),el=favEl("fav-progress-elapsed"),eta=favEl("fav-progress-eta");
    if(fill)fill.style.width=pct+"%";if(p)p.textContent=Math.round(pct)+"%";if(c)c.textContent=(d.processed??0)+" / "+(d.total??0);if(stage)stage.textContent=d.message||"Расчёт…";if(el)el.textContent=formatFavTime(d.elapsed_s);if(eta)eta.textContent=d.eta_s==null?"—":formatFavTime(d.eta_s);
}
function stopFavPolling(){if(favPollTimer){clearInterval(favPollTimer);favPollTimer=null;}}

function favDistanceMeters(a,b){
    var R=6371000,p1=Number(a[0])*Math.PI/180,p2=Number(b[0])*Math.PI/180,dp=(Number(b[0])-Number(a[0]))*Math.PI/180,dl=(Number(b[1])-Number(a[1]))*Math.PI/180;
    var h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.asin(Math.min(1,Math.sqrt(h)));
}
function favTargetHit(point){
    var lat=Number(point.lat),lon=Number(point.lon),tlat=Number(favEl("fav-target-lat")?.value),tlon=Number(favEl("fav-target-lon")?.value),radius=Number(favEl("fav-max-dist")?.value)||5000;
    return validFavCoordinates(lat,lon)&&validFavCoordinates(tlat,tlon)&&favDistanceMeters([lat,lon],[tlat,tlon])<=radius;
}
function favTrajectoryParts(points){
    if(!points||points.length<2)return {before:points||[]};
    var tlat=Number(favEl("fav-target-lat")?.value),tlon=Number(favEl("fav-target-lon")?.value),radius=Number(favEl("fav-max-dist")?.value)||5000;
    if(!validFavCoordinates(tlat,tlon))return {before:points};
    var latScale=6371000*Math.PI/180,lonScale=latScale*Math.cos(tlat*Math.PI/180);
    for(var i=0;i<points.length-1;i++){
        var a=points[i],b=points[i+1];
        if(favTargetHit(a))return {before:points.slice(0,i+1)};
        var ax=(Number(a.lon)-tlon)*Math.PI/180*lonScale,ay=(Number(a.lat)-tlat)*Math.PI/180*latScale;
        var bx=(Number(b.lon)-tlon)*Math.PI/180*lonScale,by=(Number(b.lat)-tlat)*Math.PI/180*latScale;
        var dx=bx-ax,dy=by-ay,aa=dx*dx+dy*dy;
        if(aa<1e-12)continue;
        var bb=2*(ax*dx+ay*dy),cc=ax*ax+ay*ay-radius*radius,disc=bb*bb-4*aa*cc;
        if(disc<0)continue;
        var root=Math.sqrt(disc),t1=(-bb-root)/(2*aa),t2=(-bb+root)/(2*aa),hitT=null;
        if(t1>=0&&t1<=1)hitT=t1;else if(t2>=0&&t2<=1)hitT=t2;
        if(hitT!==null){
            return {before:points.slice(0,i+1).concat([{lat:Number(a.lat)+(Number(b.lat)-Number(a.lat))*hitT,lon:Number(a.lon)+(Number(b.lon)-Number(a.lon))*hitT}])};
        }
    }
    if(favTargetHit(points[points.length-1]))return {before:points};
    return {before:points};
}
function addFavTrajectoryLine(group,points,isBest,windowIndex,candidate){
    if(!points||points.length<2)return;
    var parts=favTrajectoryParts(points),before=parts.before.map(function(p){return[p.lat,p.lon]});
    if(before.length>=2)L.polyline(before,{color:"#dc2626",weight:isBest?6:4,opacity:isBest?.95:.72}).addTo(group);
    var first=before[before.length-1];
    if(first)L.circleMarker(first,{radius:isBest?6:4,color:"#dc2626",fillColor:"#dc2626",fillOpacity:1,weight:2}).addTo(group);
    var popup="Окно "+(windowIndex+1)+"<br>Запуск: "+new Date(candidate.launch_time).toLocaleString("ru-RU")+"<br>Минимум до цели: "+Math.round(candidate.min_distance_to_target_m)+" м<br>В цели: "+(Number(candidate.time_in_target_s||0)/60).toFixed(1)+" мин";
    var hitLine=L.polyline(before,{color:"transparent",weight:12,opacity:0}).addTo(group);hitLine.bindPopup(popup);
}
function renderFavorableMap(data){
    if(!favMapReady())return;clearFavorableMap();var group=L.layerGroup().addTo(map);favTrajectoryLayer=group;var bounds=[];
    var windows=data.windows||[];windows.forEach(function(windowItem,wi){(windowItem.best_candidates||[]).forEach(function(candidate,ci){var points=candidate.trajectory&&candidate.trajectory.points||[];if(points.length<2)return;var visible=favTrajectoryParts(points).before;visible.forEach(function(p){bounds.push([p.lat,p.lon]);});var isBest=wi===0&&ci===0;addFavTrajectoryLine(group,points,isBest,wi,candidate);});});
    if(bounds.length)map.fitBounds(bounds,{padding:[40,40],maxZoom:11});
}
function formatMeters(value){var n=Number(value);if(!Number.isFinite(n))return"—";return n>=1000?(n/1000).toFixed(2)+" км":Math.round(n)+" м";}
function renderFavorableResults(data){
    var results=favEl("results"),content=favEl("result-content");if(results)results.classList.remove("hidden");var windows=data.windows||[];if(!windows.length){if(content)content.innerHTML="<div class='result-card'>Подходящих окон не найдено.</div>";return;}if(!content)return;
    content.innerHTML=windows.map(function(w,i){var best=(w.best_candidates||[])[0];if(!best)return"";var closest=best.closest_point||{},success=best.ensemble_success_rate;return '<div class="result-card"><strong>Окно #'+(i+1)+'</strong><div><b>Период:</b> '+new Date(w.window_start).toLocaleString("ru-RU")+' — '+new Date(w.window_end).toLocaleString("ru-RU")+'</div><div><b>Рекомендуемый запуск:</b> '+new Date(w.recommended_time).toLocaleString("ru-RU")+'</div><div><b>Точка:</b> '+Number(best.launch_point.lat).toFixed(5)+', '+Number(best.launch_point.lon).toFixed(5)+'</div><div><b>Минимум до цели:</b> '+formatMeters(best.min_distance_to_target_m)+'</div><div><b>В целевой области:</b> '+(Number(best.time_in_target_s||0)/60).toFixed(1)+' мин</div><div><b>Максимальное сближение:</b> '+(closest.time?new Date(closest.time).toLocaleString("ru-RU"):"—")+(closest.altitude!=null?' на высоте '+Math.round(closest.altitude)+' м':'')+'</div>'+(success!=null?'<div><b>Успешность ансамбля:</b> '+(Number(success)*100).toFixed(0)+'%</div>':'')+'</div>';}).join("");
}

async function pollFavorableJob(jobId,button){
    stopFavPolling();
    async function check(){
        try{
            var response=await fetch("/api/favorable/status/"+encodeURIComponent(jobId),{cache:"no-store"});var data=await response.json();if(!response.ok)throw new Error(data.detail||("HTTP "+response.status));
            updateFavProgress(data.progress||{});
            if(data.status==="done"){stopFavPolling();favResultData=data.result;renderFavorableResults(data.result);renderFavorableMap(data.result);setFavorableStatus(data.result.windows&&data.result.windows.length?"Готово. Выберите окно в результатах.":"Расчёт завершён: подходящих окон не найдено.");if(button)button.disabled=false;return;}
            if(data.status==="error"){stopFavPolling();setFavorableStatus("Ошибка расчёта: "+(data.error||"неизвестная ошибка"),true);if(button)button.disabled=false;return;}
        }catch(error){stopFavPolling();setFavorableStatus("Ошибка получения прогресса: "+error.message,true);if(button)button.disabled=false;return;}
    }
    await check();favPollTimer=setInterval(check,500);
}

async function calculateFavorable(){
    setFavorableMode();var targetLat=Number(favEl("fav-target-lat")?.value),targetLon=Number(favEl("fav-target-lon")?.value),launchLat=Number(favEl("fav-launch-lat")?.value),launchLon=Number(favEl("fav-launch-lon")?.value);
    if(!validFavCoordinates(targetLat,targetLon)||!validFavCoordinates(launchLat,launchLon)){setFavorableStatus("Проверьте координаты цели и области запуска.",true);return;}
    var start=favEl("fav-search-start")?.value,end=favEl("fav-search-end")?.value;if(!start||!end){setFavorableStatus("Укажите период поиска.",true);return;}
    var button=favEl("calculate-favorable");if(button)button.disabled=true;clearFavorableMap();setFavorableStatus("Запускаем расчёт…");updateFavProgress({percent:0,processed:0,total:0,message:"Запускаем расчёт…",elapsed_s:0,eta_s:null});
    try{
        var payload={target:{lat:targetLat,lon:targetLon},launch_center:{lat:launchLat,lon:launchLon},search_start:new Date(start).toISOString(),search_end:new Date(end).toISOString(),launch_radius_m:Number(favEl("fav-radius")?.value)||1000,target_radius_m:Number(favEl("fav-max-dist")?.value)||5000,time_step_hours:1,duration_hours:Number(favEl("fav-duration")?.value)||5,step_minutes:2,ascent_rate:Number(favEl("fav-ascent")?.value)||5,max_altitude:Number(favEl("fav-max-alt")?.value)||9000,start_altitude:0,launch_points_rings:2,launch_points_per_ring:12,ensemble_members:50};
        var response=await fetch("/api/favorable/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});var accepted=await response.json();if(!response.ok)throw new Error(accepted.detail||("HTTP "+response.status));
        await pollFavorableJob(accepted.job_id,button);
    }catch(error){stopFavPolling();setFavorableStatus("Ошибка запуска расчёта: "+error.message,true);if(button)button.disabled=false;}
}
function initFavorableControls(){var tab=favEl("tab-favorable"),target=favEl("fav-set-target"),launch=favEl("fav-set-launch"),calc=favEl("calculate-favorable"),radius=favEl("fav-radius"),maxDist=favEl("fav-max-dist");if(tab)tab.addEventListener("click",setFavorableMode);if(target)target.addEventListener("click",enableFavTargetSelection);if(launch)launch.addEventListener("click",enableFavLaunchSelection);if(calc)calc.addEventListener("click",calculateFavorable);if(radius)radius.addEventListener("input",updateFavLaunchCircle);if(maxDist)maxDist.addEventListener("input",function(){var lat=Number(favTargetLat?.value),lon=Number(favTargetLon?.value);if(validFavCoordinates(lat,lon))updateFavTargetMarker(lat,lon);});setFavSearchDefaults();}
document.addEventListener("DOMContentLoaded",initFavorableControls);
