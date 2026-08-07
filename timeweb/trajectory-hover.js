(()=>{
'use strict';
const MARKER_FILL='#ffd400';
const MARKER_BORDER='#111827';
function value(p,keys){for(const k of keys){const n=Number(p?.[k]);if(Number.isFinite(n))return n}return 0}
function pointMarkers(layer){
  const points=layer._trajectoryPoints;
  if(!Array.isArray(points)||points.length<2)return;
  if(layer._trajectoryPointMarkers){map.removeLayer(layer._trajectoryPointMarkers);layer._trajectoryPointMarkers=null;return;}
  const group=L.layerGroup();
  points.forEach((p,i)=>{
    const marker=L.circleMarker([Number(p.lat),Number(p.lon)],{radius:4,color:MARKER_BORDER,weight:2,fillColor:MARKER_FILL,fillOpacity:.98});
    const time=p.time?new Date(p.time).toLocaleString():'—';
    marker.bindTooltip(`<b>Точка ${i+1}</b><br>Время: ${time}<br>Высота: ${value(p,['altitude_m','altitude']).toFixed(0)} м<br>Скорость: ${value(p,['speed_mps','wind_speed_mps','ground_speed_mps']).toFixed(2)} м/с`,{direction:'top',sticky:true});
    marker.addTo(group);
  });
  group.addTo(map);layer._trajectoryPointMarkers=group;
}
function enhance(layer){
  if(!layer||layer._trajectoryEnhanced)return;
  layer._trajectoryEnhanced=true;
  layer.on('click',e=>{
    if(Array.isArray(layer._trajectoryPoints)&&layer._trajectoryPoints.length>1){
      layer.setStyle({weight:Math.max(Number(layer.options.weight)||3,6)});layer.bringToFront();
      if(typeof showTrajectoryInfo==='function')showTrajectoryInfo(layer._trajectoryPoints,layer._trajectoryTitle||'Траектория',e.originalEvent);
      pointMarkers(layer);
    }
  });
  layer.on('remove',()=>{if(layer._trajectoryPointMarkers){map.removeLayer(layer._trajectoryPointMarkers);layer._trajectoryPointMarkers=null;}});
}
const originalPolyline=L.polyline;
L.polyline=function(points,options,...rest){
  const layer=originalPolyline.call(this,points,options,...rest);
  if(Array.isArray(points)&&points.length)layer._trajectoryPoints=points.map(p=>Array.isArray(p)?{lat:Number(p[0]),lon:Number(p[1])}:p);
  enhance(layer);return layer;
};

const selectionMarkers={direct:null,back:null,target:null,launch:null};
const selectionKinds={};
function markerIcon(color){return L.divIcon({className:'weter-selection-marker',html:`<span style="display:block;width:20px;height:20px;border-radius:50% 50% 50% 0;background:${color};border:2px solid #fff;box-shadow:0 1px 5px #0008;transform:rotate(-45deg)"></span>`,iconSize:[20,20],iconAnchor:[10,20]});}
function removeDefaultMarkerAt(lat,lng){
  map.eachLayer(layer=>{
    if(!(layer instanceof L.Marker)||!layer.getLatLng)return;
    const ll=layer.getLatLng(),own=layer.options?.icon?.options?.className==='weter-selection-marker';
    if(!own&&Math.abs(ll.lat-lat)<0.00001&&Math.abs(ll.lng-lng)<0.00001)map.removeLayer(layer);
  });
}
function placeSelectionMarker(kind,lat,lng){
  if(selectionMarkers[kind])map.removeLayer(selectionMarkers[kind]);
  const colors={direct:'#16a34a',back:'#7c3aed',target:'#dc2626',launch:'#2563eb'};
  selectionMarkers[kind]=L.marker([lat,lng],{icon:markerIcon(colors[kind])}).addTo(map);
  removeDefaultMarkerAt(lat,lng);setTimeout(()=>removeDefaultMarkerAt(lat,lng),50);setTimeout(()=>removeDefaultMarkerAt(lat,lng),250);
}
function installSelectionMarkers(){
  document.querySelectorAll('.panel .secondary').forEach(button=>button.addEventListener('click',()=>{
    const panel=button.closest('.panel');if(!panel)return;let kind=null;
    if(panel.id==='direct')kind='direct';else if(panel.id==='back')kind='back';else if(panel.id==='fav')kind=button.textContent.includes('центр')?'launch':'target';
    if(kind)selectionKinds.pending=kind;
  }));
  map.on('click',e=>{const kind=selectionKinds.pending;if(!kind)return;selectionKinds.pending=null;placeSelectionMarker(kind,e.latlng.lat,e.latlng.lng);});
}

function installDocuments(){
  if(document.getElementById('weter-docs'))return;
  const style=document.createElement('style');style.id='weter-docs-style';style.textContent=`
  /* Документация является частью бокового меню, а не плавающим слоем карты. */
  .side > .weter-doc-links{position:static!important;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;float:none!important;clear:both!important;z-index:auto!important;width:100%;display:flex;gap:8px;align-items:stretch;margin:22px 0 0;padding:14px 0 2px;border-top:1px solid #e1e6ea}
  .weter-doc-btn{flex:1;min-width:0;border:1px solid #cbd3da;background:#f8fafb;color:#17202a;border-radius:9px;padding:10px 9px;font:600 12px/1.2 Inter,Arial,sans-serif;box-shadow:0 1px 4px #0001;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease,background .18s ease}
  .weter-doc-btn:hover{background:#f0f3f6;transform:translateY(-1px);box-shadow:0 3px 10px #0002}.weter-doc-btn:active{transform:translateY(0)}
  .weter-doc-modal{position:fixed;inset:0;width:100%;height:100%;height:100dvh;z-index:30000;background:rgba(15,23,42,.48);display:flex;align-items:center;justify-content:center;padding:16px;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .2s ease,visibility .2s ease}
  .weter-doc-modal.open{opacity:1;visibility:visible;pointer-events:auto}
  .weter-doc-window{width:min(920px,100%);height:min(88vh,900px);height:min(88dvh,900px);max-height:calc(100dvh - 32px);background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 18px 60px #0005;transform:translateY(10px) scale(.985);transition:transform .22s ease;position:relative;display:flex;flex-direction:column}
  .weter-doc-modal.open .weter-doc-window{transform:none}
  .weter-doc-head{flex:0 0 48px;height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid #e4e8eb;background:#fff;font:600 13px/1 Inter,Arial,sans-serif;position:relative;z-index:2}
  .weter-doc-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:8px}
  .weter-doc-close{flex:0 0 34px;width:34px;height:34px;border:1px solid #d5dbe1;border-radius:50%;background:#f7f8fa;color:#334155;font-size:22px;line-height:30px;text-align:center;padding:0;cursor:pointer;box-shadow:0 1px 4px #0002;display:flex;align-items:center;justify-content:center}
  .weter-doc-close:hover{background:#eef1f4}.weter-doc-frame{display:block;flex:1 1 auto;width:100%;height:auto;min-height:0;border:0;background:#fff}
  @media(max-width:850px){
    .side > .weter-doc-links{position:static!important;width:100%;margin:18px 0 2px;padding:12px 0 2px;gap:7px;clear:both!important}
    .weter-doc-btn{padding:10px 7px}
    .weter-doc-modal{padding:8px;align-items:center}
    .weter-doc-window{width:100%;height:calc(100dvh - 16px);max-height:none;border-radius:12px}
    .weter-doc-head{flex-basis:50px;height:50px;padding:0 10px}
    .weter-doc-close{width:38px;height:38px;flex-basis:38px;font-size:24px;line-height:34px;background:#fff;border-color:#cbd3da}
  }
  @media(max-width:380px){.weter-doc-head{flex-basis:46px;height:46px}.weter-doc-close{width:36px;height:36px;flex-basis:36px}.weter-doc-modal{padding:6px}.weter-doc-window{height:calc(100dvh - 12px)}}
  `;document.head.appendChild(style);
  const links=document.createElement('div');links.id='weter-docs';links.className='weter-doc-links';links.innerHTML='<button class="weter-doc-btn" data-doc="oznakomlenie.html">Ознакомиться</button><button class="weter-doc-btn" data-doc="fizika-processov.html">Физика процессов</button>';
  const modal=document.createElement('div');modal.className='weter-doc-modal';modal.innerHTML='<div class="weter-doc-window" role="dialog" aria-modal="true"><div class="weter-doc-head"><span class="weter-doc-title">Справочные материалы</span><button class="weter-doc-close" aria-label="Закрыть">×</button></div><iframe class="weter-doc-frame" title="Справочный материал"></iframe></div>';
  const side=document.querySelector('.side');
  if(side){side.appendChild(links)}else{document.body.appendChild(links)}
  document.body.appendChild(modal);
  const frame=modal.querySelector('iframe'),title=modal.querySelector('.weter-doc-title');
  function close(){modal.classList.remove('open');document.body.style.overflow='';frame.src=''}
  links.querySelectorAll('[data-doc]').forEach(btn=>btn.addEventListener('click',()=>{const file=btn.dataset.doc;title.textContent=file==='fizika-processov.html'?'Физика процессов':'Ознакомление с приложением';frame.src=file;modal.classList.add('open');document.body.style.overflow='hidden'}));
  modal.querySelector('.weter-doc-close').addEventListener('click',close);modal.addEventListener('click',e=>{if(e.target===modal)close()});document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
}
installSelectionMarkers();installDocuments();
})();
