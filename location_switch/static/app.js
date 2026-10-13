const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="location-token"]').content;
let busy = false, ready = false, mode = 'unknown', activeUdid = null, selectedLabel = 'Manual coordinates';
let devices = [], discoveryBusy = false;
let setup = {state:'idle',udid:null,message:''};
let mapView = null, marker = null, mapLoading = false;
let appConfig = {tile_url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',discovery_interval:30};
function message(text, error = false) { $('message').hidden = !text; $('message').textContent = text; $('message').className = error ? 'error' : ''; }
async function api(path, data) {
  const response = await fetch(path, data ? { method: 'POST', headers: {'Content-Type':'application/json','X-Location-Token':token}, body: JSON.stringify(data) } : {});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the device and coordinate values.');
  return result;
}
function coordinates() {
  const lat = $('latitude').value.trim(), lon = $('longitude').value.trim();
  if (!lat || !lon) return null;
  const latitude = Number(lat), longitude = Number(lon);
  return Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180 ? {latitude,longitude} : null;
}
function controls() {
  ready = !!devices.find(d => d.udid === $('device').value && d.ready);
  const settingUp = setup.state === 'enabling' || setup.state === 'pairing';
  $('spoof').disabled = busy || settingUp || !ready || !coordinates();
  $('restore').disabled = busy || settingUp || !ready;
  $('device').disabled = busy || settingUp || (!!activeUdid && mode !== 'real');
  $('refresh').disabled = busy || discoveryBusy;
  $('search').disabled = busy;
  const device = devices.find(d => d.udid === $('device').value);
  const needsPairing = !!device && !device.ready;
  const alreadyEnabled = device?.developer_mode === true || (setup.udid === device?.udid && setup.state === 'enabled');
  $('enable-developer-mode').disabled = busy || discoveryBusy || settingUp || !device || alreadyEnabled || mode === 'spoofed';
  $('enable-developer-mode').textContent = settingUp ? setup.state === 'pairing' ? 'Pairing…' : 'Enabling…' : needsPairing ? 'Pair iPhone' : 'Enable Dev Mode';
  $('enable-developer-mode').setAttribute('aria-label',needsPairing ? 'Pair iPhone' : 'Enable Developer Mode');
  $('enable-developer-mode').title = needsPairing ? 'Request the Trust dialog; unlock the iPhone and tap Trust.' : 'Reveal Developer Mode without Xcode; automatic enabling may restart the iPhone.';
  const setupVisible = setup.udid && (setup.udid === $('device').value || settingUp);
  $('developer-status').className = setupVisible && setup.state === 'error' && !alreadyEnabled ? 'setup-error' : '';
  $('developer-status').textContent = setupVisible && settingUp ? setup.state === 'pairing' ? 'Pairing…' : 'Enabling…' : alreadyEnabled ? 'Dev Mode on' : setupVisible && setup.state === 'error' ? 'Setup failed' : device?.developer_mode === false ? 'Dev Mode off' : 'Dev Mode unknown';
  $('developer-status').title = setupVisible ? setup.message : '';
}
function destination(manual = false) {
  if (manual) selectedLabel = 'Manual coordinates';
  const value = coordinates();
  $('selected').textContent = value ? `${selectedLabel === 'Manual coordinates' || selectedLabel === 'Map selection' ? '' : selectedLabel + ' · '}${value.latitude.toFixed(6)}, ${value.longitude.toFixed(6)}` : 'No destination';
  try { if (value) localStorage.setItem('destination', JSON.stringify({...value,label:selectedLabel})); else localStorage.removeItem('destination'); } catch {}
  controls();
  if (mapView && value) updateMap(value);
}
function renderStatus(data) {
  const previousSetup = setup.state;
  mode = data.mode; activeUdid = data.udid;
  setup = data.developer_setup || {state:'idle',udid:null,message:''};
  if (activeUdid && mode !== 'real' && devices.some(d => d.udid === activeUdid)) $('device').value = activeUdid;
  const same = !data.udid || data.udid === $('device').value;
  $('status').className = `status ${same ? mode : 'unknown'}`;
  $('status-text').textContent = same && mode === 'spoofed' ? `Spoofing · ${data.destination.latitude.toFixed(4)}, ${data.destination.longitude.toFixed(4)}` : same && mode === 'real' ? 'Real GPS' : 'Location unknown';
  if (data.error) { $('status').className = 'status error'; $('status-text').textContent = data.error; }
  controls();
  if ((previousSetup === 'enabling' || previousSetup === 'pairing') && setup.state !== 'enabling' && setup.state !== 'pairing') {
    message(setup.message, setup.state === 'error');
    if (setup.state === 'enabled' || setup.state === 'paired') refresh();
  }
  if (setup.state === 'manual' && previousSetup !== 'manual') message(setup.message);
  if (busy && data.operation_message) message(data.operation_message);
}
async function refresh(silent = false) {
  if (discoveryBusy || busy) return;
  discoveryBusy = true; controls();
  try {
    const prior = $('device').value;
    const data = await api(`/api/devices${silent ? '' : '?refresh=true'}`); devices = data.devices;
    const options = [new Option(devices.length ? 'Choose an iPhone' : 'Connect an iPhone', '')];
    for (const d of devices) options.push(new Option(`${d.name} · iOS ${d.version}${d.ready ? '' : ' · Trust required'}`, d.udid));
    const pinnedUdid = (setup.state === 'enabling' || setup.state === 'pairing') ? setup.udid : activeUdid && mode !== 'real' ? activeUdid : null;
    if (pinnedUdid && !devices.some(d => d.udid === pinnedUdid)) options.push(new Option(setup.state === 'enabling' ? 'iPhone restarting — waiting to reconnect' : 'Active iPhone disconnected', pinnedUdid));
    $('device').replaceChildren(...options);
    $('device').value = pinnedUdid || (devices.some(d => d.udid === prior) ? prior : devices.length === 1 ? devices[0].udid : '');
    const state = await api('/api/status'); renderStatus(state);
    if (activeUdid && !devices.some(d => d.udid === activeUdid) && setup.state !== 'enabling') { $('status').className = 'status error'; $('status-text').textContent = 'iPhone disconnected · location status unknown. Reconnect and restore real location.'; }
    if (!silent) message(devices.length ? '' : 'No iPhone found. Connect by USB, unlock it, and tap Trust.');
  } catch (err) {
    devices = []; controls(); $('status').className = 'status error'; $('status-text').textContent = 'Device discovery unavailable';
    if (!silent) message(err.message, true);
  } finally { discoveryBusy = false; controls(); }
}
$('refresh').addEventListener('click', () => refresh());
$('enable-developer-mode').addEventListener('click', async () => {
  const udid = $('device').value;
  const needsPairing = !devices.find(device=>device.udid === udid)?.ready;
  busy = true; controls(); message('Starting Developer Mode setup…');
  try {
    setup = await api(needsPairing ? '/api/device/pair' : '/api/developer-mode/enable', {udid});
    message(setup.message);
  } catch (err) { message(err.message,true); }
  finally { busy = false; controls(); }
});
$('device').addEventListener('change', () => { renderStatus({mode:'unknown',udid:null}); message(''); });
for (const field of ['latitude','longitude']) $(field).addEventListener('input', () => destination(true));
$('search-form').addEventListener('submit', async event => {
  event.preventDefault(); busy = true; controls(); message('Searching…'); $('results').hidden = true;
  try {
    const {results} = await api('/api/search', {query:$('address').value.trim()});
    $('results').replaceChildren();
    for (const result of results) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = result.label;
      button.addEventListener('click', () => {
        $('latitude').value = result.latitude; $('longitude').value = result.longitude; selectedLabel = result.label;
        destination(); $('results').hidden = true; message('Destination selected.');
      }); $('results').append(button);
    }
    $('results').hidden = !results.length;
    message(results.length ? 'Select the matching address below.' : 'No matching address. Add the city and country, or enter coordinates.');
  } catch (err) { message(err.message,true); }
  finally { busy = false; controls(); }
});
async function change(action) {
  busy = true; controls(); message(action === 'spoof' ? 'Applying location…' : 'Restoring real location…');
  try {
    const data = {udid:$('device').value};
    if (action === 'spoof') Object.assign(data, coordinates(), {label:selectedLabel});
    renderStatus(await api(`/api/${action}`,data));
    message(action === 'spoof' ? 'Location applied.' : 'Simulation cleared.');
  } catch (err) { message(err.message,true); try {renderStatus(await api('/api/status'));} catch { $('status-text').textContent = 'Server unavailable · location status unknown'; } }
  finally {busy = false; controls();}
}
$('spoof').addEventListener('click', () => change('spoof'));
$('restore').addEventListener('click', () => change('restore'));
try { const saved = JSON.parse(localStorage.getItem('destination')); if(saved) { $('latitude').value = saved.latitude; $('longitude').value = saved.longitude; selectedLabel = saved.label; destination(); } } catch {}
refresh();
setInterval(async () => { if (document.hidden) return; try { renderStatus(await api('/api/status')); } catch { devices = []; controls(); $('status-text').textContent = 'Server unavailable'; } }, 2000);
api('/api/config').then(config => {appConfig=config;}).catch(() => {}).finally(() => {
  setInterval(() => {if(!document.hidden) refresh(true);}, appConfig.discovery_interval * 1000);
});

function updateMap(value) {
  const point = [value.latitude, value.longitude];
  if (marker) marker.setLatLng(point);
  else marker = L.circleMarker(point, {radius:7,color:'#fff',weight:3,fillColor:'#175cff',fillOpacity:1}).addTo(mapView);
  if (!$('map-panel').hidden) mapView.panTo(point, {animate:false});
}
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((resolve,reject) => {
    const css = document.createElement('link'); css.rel='stylesheet'; css.href='/static/vendor/leaflet/leaflet.css'; document.head.append(css);
    const script = document.createElement('script'); script.src='/static/vendor/leaflet/leaflet.js';
    script.onload=resolve; script.onerror=() => {script.remove();css.remove();reject(new Error('Map library unavailable. Coordinates still work.'));};
    document.head.append(script);
  });
}
$('map-toggle').addEventListener('click', async () => {
  if (mapLoading) return;
  if (!$('map-panel').hidden) {
    $('map-panel').hidden=true; $('map-toggle').textContent='Show map'; $('map-toggle').setAttribute('aria-expanded','false');
    if(mapView) {mapView.remove();$('map').replaceChildren();$('map').className='';$('map').removeAttribute('style');mapView=null;marker=null;}
    return;
  }
  mapLoading=true; $('map-toggle').disabled=true;
  try {
    await loadLeaflet();
    $('map-panel').hidden=false; $('map-toggle').textContent='Hide map'; $('map-toggle').setAttribute('aria-expanded','true');
    const value = coordinates();
    mapView = L.map('map',{zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false,scrollWheelZoom:false,zoomControl:false}).setView(value ? [value.latitude,value.longitude] : [20,0], value ? 14 : 2);
    L.control.zoom({position:'topright'}).addTo(mapView);
    L.tileLayer(appConfig.tile_url, {maxZoom:19,keepBuffer:0,updateWhenIdle:true,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).on('tileerror',() => {$('map-status').textContent='Map tiles unavailable. Coordinate selection still works.';}).addTo(mapView);
    if(value) updateMap(value);
    mapView.on('click',event => {
      if(busy || setup.state === 'enabling') return;
      $('latitude').value=Math.max(-90,Math.min(90,event.latlng.lat)).toFixed(6);
      $('longitude').value=(((event.latlng.lng+180)%360+360)%360-180).toFixed(6);
      selectedLabel='Map selection'; destination(); message('');
    });
  } catch(err) { message(err.message,true); $('map-panel').hidden=true; $('map-toggle').textContent='Show map'; $('map-toggle').setAttribute('aria-expanded','false'); }
  finally {mapLoading=false;$('map-toggle').disabled=false;}
});
