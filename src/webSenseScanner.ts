import { Html5Qrcode, Html5QrcodeSupportedFormats } from 'html5-qrcode';

// The bundled Capacitor web scanner does not provide a styled camera chooser
// or propagate camera-start failures. Keep web camera lifecycle explicit here.
export function scanWebSenseRoom(): Promise<string> {
  if (!navigator.mediaDevices?.getUserMedia) {
    return Promise.reject(new Error('Camera access needs localhost or HTTPS. You can paste the room link instead.'));
  }
  return new Promise((resolve, reject) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'sense-camera-dialog';
    dialog.setAttribute('aria-labelledby', 'sense-camera-title');
    dialog.innerHTML = `<h2 id="sense-camera-title">Scan your room QR</h2>
      <p>Show the SenseRobot game-room QR to your camera.</p>
      <label for="sense-camera-choice">Camera</label>
      <select id="sense-camera-choice" hidden></select>
      <div id="sense-camera-preview"></div>
      <p role="status" id="sense-camera-status">Camera access starts when you choose Start camera.</p>
      <button type="button" class="primary wide" id="sense-camera-start">Start camera</button>
      <button type="button" class="ghost wide" id="sense-camera-cancel">Cancel & use a room link</button>`;
    document.body.appendChild(dialog);
    const select = dialog.querySelector<HTMLSelectElement>('select')!;
    const status = dialog.querySelector<HTMLElement>('[role="status"]')!;
    const start = dialog.querySelector<HTMLButtonElement>('#sense-camera-start')!;
    const cancel = dialog.querySelector<HTMLButtonElement>('#sense-camera-cancel')!;
    let scanner: Html5Qrcode | null = null;
    let settled = false;
    let switching = false;
    let cameraTask: Promise<void> | null = null;

    async function finish(value?: string, error?: Error) {
      if (settled) return;
      settled = true;
      dialog.close();
      await cameraTask?.catch(() => {});
      try { if (scanner?.isScanning) await scanner.stop(); }
      catch { /* The camera may already have stopped. */ }
      dialog.remove();
      if (error) reject(error);
      else resolve(value!);
    }

    async function startCamera(cameraId: string) {
      if (switching || settled || !scanner) return;
      switching = true; select.disabled = true;
      try {
        if (scanner.isScanning) await scanner.stop();
        if (settled) return;
        await scanner.start(cameraId, {
          fps: 10,
          qrbox: (width, height) => { const size = Math.min(250, Math.floor(Math.min(width, height) * .75)); return { width: size, height: size }; },
        }, decoded => { void finish(decoded); }, () => { /* Keep looking for a QR. */ });
        if (settled) { if (scanner.isScanning) await scanner.stop(); return; }
        status.textContent = 'Camera ready. Hold the room QR steady in view.';
      } catch (cause) {
        if (!settled) void finish(undefined, new Error(`Could not start the camera: ${cause instanceof Error ? cause.message : String(cause)}. Paste the room link instead.`));
      } finally { switching = false; select.disabled = false; }
    }

    start.onclick = async () => {
      start.disabled = true;
      status.textContent = 'Waiting for camera permission…';
      try {
        const cameras = await Html5Qrcode.getCameras();
        if (settled) return;
        if (!cameras.length) throw new Error('No camera found');
        cameras.forEach(camera => {
          const option = document.createElement('option');
          option.value = camera.id; option.textContent = camera.label || `Camera ${select.length + 1}`;
          select.appendChild(option);
        });
        const preferred = cameras.find(camera => /back|rear|environment/i.test(camera.label)) || cameras[0];
        select.value = preferred.id; select.hidden = false; start.hidden = true;
        scanner = new Html5Qrcode('sense-camera-preview', { formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE], verbose: false });
        cameraTask = startCamera(preferred.id);
        await cameraTask;
      } catch (cause) {
        void finish(undefined, new Error(`Camera access failed: ${cause instanceof Error ? cause.message : String(cause)}. Allow camera access or paste the room link.`));
      }
    };
    select.onchange = () => { cameraTask = startCamera(select.value); };
    cancel.onclick = () => { void finish(undefined, new Error('Scan cancelled. You can paste the room link below.')); };
    dialog.addEventListener('cancel', event => { event.preventDefault(); cancel.click(); });
    dialog.showModal();
  });
}
