/* NASA GIBS 卫星气溶胶 AOD（MODIS Terra+Aqua 联合，真实卫星测量，逐日）
   原生最高 z6（MODIS 1km），maxNativeZoom 后放大展示；日产品约 1 天延迟取昨日 */
let mapRef = null, layer = null;

export function initGibs(map) { mapRef = map; }

export function toggle(onOff) {
  if (!onOff) {
    if (layer) { mapRef.removeLayer(layer); layer = null; }
    return;
  }
  if (layer) return;
  const d = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  layer = L.tileLayer(
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_Value_Added_AOD/default/${d}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`,
    { maxNativeZoom: 6, maxZoom: 12, opacity: 0.75, tileSize: 256 });
  layer.addTo(mapRef);
}
