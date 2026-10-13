const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="location-token"]').content;
let busy = false, ready = false, mode = 'unknown', activeUdid = null, selectedLabel = 'Manual coordinates';
let devices = [], discoveryBusy = false;
let setup = {state:'idle',udid:null,message:''};
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
  const settingUp = setup.state === 'enabling';
  $('spoof').disabled = busy || settingUp || !ready || !coordinates();
  $('restore').disabled = busy || settingUp || !ready;
  $('device').disabled = busy || settingUp || (!!activeUdid && mode !== 'real');
  $('refresh').disabled = busy || discoveryBusy;
  $('search').disabled = busy;
  const device = devices.find(d => d.udid === $('device').value);
  const alreadyEnabled = device?.developer_mode === true || (setup.udid === device?.udid && setup.state === 'enabled');
  $('enable-developer-mode').disabled = busy || discoveryBusy || settingUp || !ready || alreadyEnabled || mode === 'spoofed';
  $('enable-developer-mode').textContent = settingUp ? 'Enabling…' : 'Enable Developer Mode';
  const setupVisible = setup.udid && (setup.udid === $('device').value || settingUp);
  $('developer-status').className = setupVisible && setup.state === 'error' && !alreadyEnabled ? 'setup-error' : '';
  $('developer-status').textContent = setupVisible && settingUp ? setup.message : alreadyEnabled ? 'Developer Mode enabled' : setupVisible && setup.state === 'error' ? setup.message : device?.developer_mode === false ? 'Developer Mode is off' : 'Developer Mode status unknown';
}
function destination(manual = false) {
  if (manual) selectedLabel = 'Manual coordinates';
  const value = coordinates();
  $('selected').textContent = value ? `${selectedLabel} · ${value.latitude.toFixed(6)}, ${value.longitude.toFixed(6)}` : 'No destination selected';
  try { if (value) localStorage.setItem('destination', JSON.stringify({...value,label:selectedLabel})); else localStorage.removeItem('destination'); } catch {}
  controls();
}
function renderStatus(data) {
  const previousSetup = setup.state;
  mode = data.mode; activeUdid = data.udid;
  setup = data.developer_setup || {state:'idle',udid:null,message:''};
  if (activeUdid && mode !== 'real' && devices.some(d => d.udid === activeUdid)) $('device').value = activeUdid;
  const same = !data.udid || data.udid === $('device').value;
  $('status').className = `status ${same ? mode : 'unknown'}`;
  $('status-text').textContent = same && mode === 'spoofed' ? `Spoofing · ${data.destination.latitude.toFixed(6)}, ${data.destination.longitude.toFixed(6)}` : same && mode === 'real' ? 'Real location · simulation cleared' : 'Location status unknown';
  if (data.error) { $('status').className = 'status error'; $('status-text').textContent = data.error; }
  controls();
  if (previousSetup === 'enabling' && setup.state !== 'enabling') {
    message(setup.message, setup.state === 'error');
    if (setup.state === 'enabled') refresh(true);
  }
}
async function refresh(silent = false) {
  if (discoveryBusy || busy) return;
  discoveryBusy = true; controls();
  try {
    const prior = $('device').value;
    const data = await api('/api/devices'); devices = data.devices;
    const options = [new Option(devices.length ? 'Choose an iPhone' : 'Connect an iPhone', '')];
    for (const d of devices) options.push(new Option(`${d.name} · iOS ${d.version}${d.ready ? '' : ' · Trust required'}`, d.udid));
    const pinnedUdid = setup.state === 'enabling' ? setup.udid : activeUdid && mode !== 'real' ? activeUdid : null;
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
  busy = true; controls(); message('Starting Developer Mode setup…');
  try {
    setup = await api('/api/developer-mode/enable', {udid});
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
        destination(); $('results').hidden = true; message('Destination selected. Use spoofed location to apply it.');
      }); $('results').append(button);
    }
    $('results').hidden = !results.length;
    message(results.length ? 'Select the matching address below.' : 'No matching address. Add the city and country, or enter coordinates.');
  } catch (err) { message(err.message,true); }
  finally { busy = false; controls(); }
});
async function change(action) {
  busy = true; controls(); message(action === 'spoof' ? 'Connecting and applying location…' : 'Clearing simulated location…');
  try {
    const data = {udid:$('device').value};
    if (action === 'spoof') Object.assign(data, coordinates(), {label:selectedLabel});
    renderStatus(await api(`/api/${action}`,data));
    message(action === 'spoof' ? 'Spoofed location applied. Keep the app running and your iPhone connected.' : 'Simulation cleared. Your iPhone’s Location Services now uses its real GPS.');
  } catch (err) { message(err.message,true); try {renderStatus(await api('/api/status'));} catch { $('status-text').textContent = 'Server unavailable · location status unknown'; } }
  finally {busy = false; controls();}
}
$('spoof').addEventListener('click', () => change('spoof'));
$('restore').addEventListener('click', () => change('restore'));
try { const saved = JSON.parse(localStorage.getItem('destination')); if(saved) { $('latitude').value = saved.latitude; $('longitude').value = saved.longitude; selectedLabel = saved.label; destination(); } } catch {}
refresh();
setInterval(async () => { if (busy) return; try { renderStatus(await api('/api/status')); } catch { devices = []; controls(); $('status-text').textContent = 'Server unavailable · location status unknown'; } }, 2000);
setInterval(() => refresh(true), 6000);
