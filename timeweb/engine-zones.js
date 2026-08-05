/* Weter zones compatibility module. */
window.WeterZones = window.WeterZones || {};
window.WeterZones.parseTargetPolygon = function () {
  var el = document.getElementById('fpolygon');
  if (!el || !el.value.trim()) return null;
  var value = JSON.parse(el.value);
  if (!Array.isArray(value) || value.length < 3) throw new Error('target polygon: нужно минимум 3 точки');
  return value;
};
window.WeterZones.parseZones = function (id) {
  var el = document.getElementById(id);
  if (!el || !el.value.trim()) return [];
  var value = JSON.parse(el.value);
  if (!Array.isArray(value)) throw new Error(id + ': ожидается массив координат');
  return value.length && Array.isArray(value[0]) ? value : [value];
};
