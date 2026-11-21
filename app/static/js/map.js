/* All user text enters the DOM through textContent, never popup HTML strings. */
"use strict";
(async () => {
  const container = document.getElementById("assessment-map");
  const status = document.getElementById("map-status");
  const tileButton = document.getElementById("load-tiles");
  if (!container) return;
  const label = value => value.replaceAll("_", " ");
  const append = (parent, tag, value) => {
    const element = document.createElement(tag);
    element.textContent = value;
    parent.append(element);
    return element;
  };
  const observation = m => `${m.value} ${m.unit} · ${label(m.type)} · ${label(m.quality)} · ${m.status} · ${m.synthetic ? "Synthetic" : "Real"}. Source: ${m.source}. Start: ${m.date}`;
  const popup = b => {
    const root = document.createElement("div");
    root.className = "map-popup";
    append(root, "h3", `${b.code} · ${b.name}`);
    append(root, "p", b.synthetic ? "Synthetic — fictional record" : "Real record");
    append(root, "p", `Priority: ${label(b.priority)}. ${b.reason}`);
    append(root, "p", `Next action: ${b.next_action}`);
    append(root, "p", `Missing: ${b.missing.join("; ") || "No listed gaps; qualified assessment still required."}`);
    append(root, "h3", "Building evidence in selected track");
    if (!b.evidence.length) append(root, "p", "No measurement. Source/date unknown.");
    b.evidence.forEach(m => append(root, "p", observation(m)));
    append(root, "h3", "Regional context — not a building measurement");
    b.contexts.forEach(a => append(root, "p", `${a.code} · ${a.status}. Source: ${a.source}. Date: ${a.date}. ${a.synthetic ? "Synthetic" : "Real"}.`));
    if (!b.contexts.length) append(root, "p", "No survey-area association.");
    append(root, "a", "Open building record").href = b.url;
    return root;
  };
  try {
    if (!window.L) throw new Error("Leaflet unavailable");
    const response = await fetch(container.dataset.source, {credentials: "same-origin", headers: {Accept: "application/json"}});
    if (!response.ok || response.redirected) throw new Error("Data unavailable");
    const data = await response.json();
    container.replaceChildren();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const map = L.map(container, {zoomAnimation: !reduced, fadeAnimation: !reduced, markerZoomAnimation: !reduced}).setView([0, 0], 2);
    const surveys = L.featureGroup().addTo(map);
    const priorities = L.featureGroup().addTo(map);
    const gaps = L.featureGroup();
    data.areas.forEach(area => {
      if (!area.geometry) return;
      const root = document.createElement("div");
      root.className = "map-popup";
      append(root, "h3", `${area.code} · ${area.name}`);
      append(root, "p", `${area.synthetic ? "Synthetic" : "Real"} · ${area.quality}. Regional context only.`);
      append(root, "p", area.context);
      append(root, "p", `Source: ${area.source}. Date: ${area.date}`);
      area.evidence.forEach(m => append(root, "p", observation(m)));
      if (!area.evidence.length) append(root, "p", "No survey-point measurements available.");
      L.geoJSON(area.geometry, {style: {color: "#125e69", weight: 2, fillOpacity: 0.07}}).bindPopup(root).addTo(surveys);
    });
    data.buildings.forEach(b => {
      if (b.latitude === null || b.longitude === null) return;
      const symbol = {priority: "P", standard: "S", unknown: "?"}[b.priority] || "?";
      const icon = L.divIcon({className: `building-marker ${b.priority}`, html: symbol, iconSize: [26, 26], iconAnchor: [13, 13]});
      L.marker([b.latitude, b.longitude], {icon, title: `${b.code}: ${b.priority}`, alt: `${b.code}: ${b.priority}`, keyboard: true}).bindPopup(popup(b), {maxWidth: 360}).addTo(priorities);
      if (b.coverage_gap) {
        const gapIcon = L.divIcon({className: "gap-marker", html: "<span>G</span>", iconSize: [38, 38], iconAnchor: [19, 19]});
        L.marker([b.latitude, b.longitude], {icon: gapIcon, title: `${b.code}: measurement coverage gap`, keyboard: true}).bindPopup(popup(b), {maxWidth: 360}).addTo(gaps);
      }
    });
    data.points.forEach(point => {
      const root = document.createElement("div");
      root.className = "map-popup";
      append(root, "h3", point.code);
      append(root, "p", `${point.synthetic ? "Synthetic" : "Real"} survey point — not a building measurement.`);
      point.evidence.forEach(m => append(root, "p", observation(m)));
      if (!point.evidence.length) append(root, "p", "No measurements. Source/date unknown.");
      const icon = L.divIcon({className: "building-marker survey-point", html: "R", iconSize: [26, 26], iconAnchor: [13, 13]});
      L.marker([point.latitude, point.longitude], {icon, title: `${point.code}: regional survey point`, keyboard: true}).bindPopup(root).addTo(surveys);
    });
    const bounds = L.featureGroup([surveys, priorities]).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, {padding: [30, 30], maxZoom: 15, animate: false});
    Object.entries({surveys, priorities, gaps}).forEach(([name, layer]) => {
      const control = document.getElementById(`layer-${name}`);
      control.disabled = false;
      control.addEventListener("change", () => control.checked ? layer.addTo(map) : map.removeLayer(layer));
    });
    status.textContent = `Map ready without background tiles. ${data.unmapped} buildings have unknown coordinates and remain in the list.`;
    tileButton.disabled = false;
    tileButton.addEventListener("click", () => {
      tileButton.disabled = true;
      tileButton.textContent = "OpenStreetMap background requested";
      status.textContent = "Loading optional background. Evidence layers and the list remain available.";
      let failed = false;
      const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
      tiles.on("tileerror", () => { failed = true; status.textContent = "Background tiles unavailable. Evidence layers and the list still work."; });
      tiles.on("load", () => { if (!failed) status.textContent = "Background loaded. Evidence remains separate from the base map."; });
      tiles.addTo(map);
    }, {once: true});
  } catch (error) {
    status.textContent = "Interactive map unavailable. Use the evidence lists below, or reload after signing in.";
    container.replaceChildren();
    append(container, "p", "Your building and survey evidence is available in the lists below.");
  }
})();
