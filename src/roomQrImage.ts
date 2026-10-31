/** Decode locally using the same QR library as the web camera scanner. */
let imageSequence = 0;
export async function readRoomQrImage(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error('Choose a QR photo or screenshot.');
  if (file.size > 20 * 1024 * 1024) throw new Error('Choose an image smaller than 20 MB.');
  const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import('html5-qrcode');
  const host = document.createElement('div');
  host.id = `room-qr-image-${++imageSequence}`;
  host.style.cssText = 'position:fixed;left:-10000px;top:0;width:800px;pointer-events:none';
  host.setAttribute('aria-hidden', 'true');
  document.body.append(host);
  let scanner: InstanceType<typeof Html5Qrcode> | undefined;
  try {
    scanner = new Html5Qrcode(host.id, { formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE], verbose: false });
    return await scanner.scanFile(file, false);
  }
  catch { throw new Error('No readable QR found. Crop to one QR code, use a clearer image, or scan it with the camera.'); }
  finally { try { scanner?.clear(); } finally { host.remove(); } }
}
