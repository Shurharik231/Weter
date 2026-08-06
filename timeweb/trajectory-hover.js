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
    const marker=L.circleMarker([Number(p.lat),Number(p.lon)],{
      radius:4,
      color:MARKER_BORDER,
      weight:2,
      fillColor:MARKER_FILL,
      fillOpacity:.98
    });
    const time=p.time?new Date(p.time).toLocaleString():'—';
    marker.bindTooltip(
      `<b>Точка ${i+1}</b><br>Время: ${time}<br>Высота: ${value(p,['altitude_m','altitude']).toFixed(0)} м<br>Скорость: ${value(p,['speed_mps','wind_speed_mps','ground_speed_mps']).toFixed(2)} м/с`,
      {direction:'top',sticky:true}
    );
    marker.addTo(group);
  });
  group.addTo(map);
  layer._trajectoryPointMarkers=group;
}
function enhance(layer){
  if(!layer||layer._trajectoryEnhanced)return;
  layer._trajectoryEnhanced=true;
  layer.on('click',e=>{
    if(Array.isArray(layer._trajectoryPoints)&&layer._trajectoryPoints.length>1){
      layer.setStyle({weight:Math.max(Number(layer.options.weight)||3,6)});
      layer.bringToFront();
      if(typeof showTrajectoryInfo==='function')showTrajectoryInfo(layer._trajectoryPoints,layer._trajectoryTitle||'Траектория',e.originalEvent);
      pointMarkers(layer);
    }
  });
  layer.on('remove',()=>{
    if(layer._trajectoryPointMarkers){map.removeLayer(layer._trajectoryPointMarkers);layer._trajectoryPointMarkers=null;}
  });
}
const originalPolyline=L.polyline;
L.polyline=function(points,options,...rest){
  const layer=originalPolyline.call(this,points,options,...rest);
  if(Array.isArray(points)&&points.length){
    layer._trajectoryPoints=points.map(p=>Array.isArray(p)?{lat:Number(p[0]),lon:Number(p[1])}:p);
  }
  enhance(layer);
  return layer;
};
})();
