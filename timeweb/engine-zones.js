/* Weter optional zone extension.
 *
 * The base engine already contains the polygon / zone primitives. This file is
 * intentionally kept as a small, syntax-safe extension point so it cannot
 * break the whole application before the optional zone UI is configured.
 */
(() => {
  'use strict';

  const parseZoneText = (id) => {
    const el = document.getElementById(id);
    if (!el || !el.value.trim()) return [];
    let value;
    try {
      value = JSON.parse(el.value);
    } catch (err) {
      throw new Error(`${id}: некорректный JSON`);
    }
    if (!Array.isArray(value)) {
      throw new Error(`${id}: ожидается массив координат`);
    }
    return value.length && Array.isArray(value[0]) ? value : [value];
  };

  // Expose parsing helpers for the main engine without replacing its solver.
  window.WeterZones = {
    parseTargetPolygon() {
      const el = document.getElementById('fpolygon');
      if (!el || !el.value.trim()) return null;
      let value;
      try {
        value = JSON.parse(el.value);
      } catch (err) {
        throw new Error('target polygon: некорректный JSON');
      }
      if (!Array.isArray(value) || value.length < 3) {
        throw new Error('target polygon: нужно минимум 3 точки');
      }
      return value;
    },

    restrictedZones() {
      return parseZoneText('frestricted');
    },

    hazardZones() {
      return parseZoneText('fhazards');
    }
  };
})();
