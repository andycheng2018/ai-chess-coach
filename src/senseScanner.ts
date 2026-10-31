import {
  CapacitorBarcodeScanner,
  CapacitorBarcodeScannerCameraDirection,
  CapacitorBarcodeScannerScanOrientation,
  type CapacitorBarcodeScannerTypeHint,
} from '@capacitor/barcode-scanner';
import { Capacitor } from '@capacitor/core';

const QR_CODE = 0 as CapacitorBarcodeScannerTypeHint;

export async function scanSenseRoomUrl(instructions = 'Scan the SenseRobot room QR code'): Promise<string> {
  if (!Capacitor.isNativePlatform()) {
    const { scanWebSenseRoom } = await import('./webSenseScanner');
    return scanWebSenseRoom();
  }
  const result = await CapacitorBarcodeScanner.scanBarcode({
    hint: QR_CODE,
    cameraDirection: CapacitorBarcodeScannerCameraDirection.BACK,
    scanOrientation: CapacitorBarcodeScannerScanOrientation.ADAPTIVE,
    scanInstructions: instructions,
  });

  const rawValue = result.ScanResult?.trim();

  if (!rawValue) {
    throw new Error('No QR code was scanned.');
  }

  return rawValue;
}
