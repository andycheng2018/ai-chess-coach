import {
  CapacitorBarcodeScanner,
  CapacitorBarcodeScannerCameraDirection,
  CapacitorBarcodeScannerScanOrientation,
  type CapacitorBarcodeScannerTypeHint,
} from '@capacitor/barcode-scanner';

import {
  joinSenseRoom,
  parseSenseRoomUrl,
  type BotRuntimeStatus,
} from './botControl';

const QR_CODE = 0 as CapacitorBarcodeScannerTypeHint;

export async function scanSenseRoom(): Promise<BotRuntimeStatus> {
  const result = await CapacitorBarcodeScanner.scanBarcode({
    hint: QR_CODE,
    cameraDirection: CapacitorBarcodeScannerCameraDirection.BACK,
    scanOrientation: CapacitorBarcodeScannerScanOrientation.ADAPTIVE,
    scanInstructions: 'Scan the SenseRobot room QR code',
  });

  const rawValue = result.ScanResult?.trim();

  if (!rawValue) {
    throw new Error('No QR code was scanned.');
  }

  const room = parseSenseRoomUrl(rawValue);

  return joinSenseRoom(
    room.challengeId,
    room.color,
  );
}