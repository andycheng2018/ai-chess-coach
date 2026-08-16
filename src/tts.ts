import type { CoachLanguage } from './coach';

const CONTROL_URL =
  import.meta.env.VITE_BOT_CONTROL_URL ||
  'http://127.0.0.1:8765';

let activeRequest: AbortController | null = null;

let audioContext: AudioContext | null = null;
let activeSource: AudioBufferSourceNode | null = null;

/**
 * iOS/WKWebView usually wants audio to be unlocked
 * from an actual user gesture.
 *
 * Call this when the user turns Voice ON.
 */
export async function unlockCoachAudio(): Promise<void> {
  try {
    if (!audioContext) {
      audioContext = new AudioContext();
    }

    if (audioContext.state === 'suspended') {
      await audioContext.resume();
    }

    console.log(
      '[TTS] Audio unlocked:',
      audioContext.state,
    );
  } catch (error) {
    console.warn(
      '[TTS] Could not unlock WebAudio:',
      error,
    );
  }
}

const EN_PIECES: Record<string, string> = {
  K: 'king',
  Q: 'queen',
  R: 'rook',
  B: 'bishop',
  N: 'knight',
};

const ZH_PIECES: Record<string, string> = {
  K: '王',
  Q: '后',
  R: '车',
  B: '象',
  N: '马',
};

const ZH_RANKS: Record<string, string> = {
  '1': '一',
  '2': '二',
  '3': '三',
  '4': '四',
  '5': '五',
  '6': '六',
  '7': '七',
  '8': '八',
};

function squareForSpeech(
  square: string,
  language: CoachLanguage,
): string {
  const file = square[0].toUpperCase();
  const rank = square[1];

  if (language === 'zh-CN') {
    return `${file} ${ZH_RANKS[rank] || rank}`;
  }

  // The space makes ElevenLabs say:
  // "g three" rather than trying to read "g3"
  return `${file} ${rank}`;
}

function sanToSpeech(
  rawSan: string,
  language: CoachLanguage,
): string {
  let san = rawSan;

  let ending = '';

  if (san.endsWith('#')) {
    ending =
      language === 'zh-CN'
        ? '，将死'
        : ', checkmate';

    san = san.slice(0, -1);
  } else if (san.endsWith('+')) {
    ending =
      language === 'zh-CN'
        ? '，将军'
        : ', check';

    san = san.slice(0, -1);
  }

  // Castling
  if (
    san === 'O-O-O' ||
    san === '0-0-0'
  ) {
    return (
      (language === 'zh-CN'
        ? '后翼易位'
        : 'castles queenside') +
      ending
    );
  }

  if (
    san === 'O-O' ||
    san === '0-0'
  ) {
    return (
      (language === 'zh-CN'
        ? '王翼易位'
        : 'castles kingside') +
      ending
    );
  }

  // Promotion
  let promotionPiece: string | null =
    null;

  const promotionMatch =
    san.match(/=([QRBN])$/i);

  if (promotionMatch) {
    promotionPiece =
      promotionMatch[1].toUpperCase();

    san = san.replace(
      /=([QRBN])$/i,
      '',
    );
  }

  // Piece moves:
  // Nf3
  // Nxg3
  // Nbd2
  // R1e2
  // Qxd5
  const pieceMove = san.match(
    /^([KQRBN])([a-h1-8]{0,2})(x?)([a-h][1-8])$/i,
  );

  if (pieceMove) {
    const piece =
      pieceMove[1].toUpperCase();

    const capture =
      pieceMove[3] === 'x';

    const destination =
      squareForSpeech(
        pieceMove[4],
        language,
      );

    if (language === 'zh-CN') {
      const pieceName =
        ZH_PIECES[piece];

      return (
        `${pieceName}${
          capture ? '吃到' : '走到'
        }${destination}` +
        ending
      );
    }

    const pieceName =
      EN_PIECES[piece];

    return (
      `${pieceName} ${
        capture ? 'takes' : 'to'
      } ${destination}` +
      ending
    );
  }

  // Pawn capture:
  // exd5
  const pawnCapture =
    san.match(
      /^[a-h]x([a-h][1-8])$/i,
    );

  if (pawnCapture) {
    const destination =
      squareForSpeech(
        pawnCapture[1],
        language,
      );

    let result =
      language === 'zh-CN'
        ? `兵吃到${destination}`
        : `pawn takes ${destination}`;

    if (promotionPiece) {
      result +=
        language === 'zh-CN'
          ? `，升变为${
              ZH_PIECES[promotionPiece]
            }`
          : `, promotes to ${
              EN_PIECES[promotionPiece]
            }`;
    }

    return result + ending;
  }

  // Pawn promotion:
  // e8=Q
  if (
    promotionPiece &&
    /^[a-h][1-8]$/i.test(san)
  ) {
    const destination =
      squareForSpeech(
        san,
        language,
      );

    if (language === 'zh-CN') {
      return (
        `兵走到${destination}，升变为${
          ZH_PIECES[promotionPiece]
        }` + ending
      );
    }

    return (
      `pawn to ${destination}, promotes to ${
        EN_PIECES[promotionPiece]
      }` + ending
    );
  }

  return rawSan;
}

function makeSpeechFriendly(
  text: string,
  language: CoachLanguage,
): string {
  /*
   * Matches chess SAN inside normal sentences.
   *
   * Examples:
   * Nf3
   * Nxg3
   * Qxd5+
   * Nbd2
   * exd5
   * e8=Q
   * O-O
   * O-O-O
   */
  const sanPattern =
    /(^|[^A-Za-z0-9])((?:O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h1-8]{0,2}x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?|[a-h][1-8]=[QRBN][+#]?))(?=$|[^A-Za-z0-9])/gi;

  return text.replace(
    sanPattern,
    (
      _match,
      prefix: string,
      san: string,
    ) =>
      `${prefix}${sanToSpeech(
        san,
        language,
      )}`,
  );
}

function browserSpeak(
  text: string,
  language: CoachLanguage,
) {
  if (!('speechSynthesis' in window)) {
    return;
  }

  window.speechSynthesis.cancel();

  const utterance =
    new SpeechSynthesisUtterance(text);

  utterance.lang =
    language === 'zh-CN'
      ? 'zh-CN'
      : 'en-US';

  utterance.rate =
    language === 'zh-CN'
      ? 0.96
      : 1.0;

  const voices =
    window.speechSynthesis.getVoices();

  const preferredVoice =
    voices.find((voice) =>
      language === 'zh-CN'
        ? voice.lang
            .toLowerCase()
            .startsWith('zh')
        : voice.lang
            .toLowerCase()
            .startsWith('en'),
    );

  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }

  console.warn(
    '[TTS] Using browser fallback voice.',
  );

  window.speechSynthesis.speak(
    utterance,
  );
}

export function stopCoachSpeech() {
  activeRequest?.abort();
  activeRequest = null;

  if (activeSource) {
    try {
      activeSource.stop();
    } catch {
      // Already stopped.
    }

    activeSource.disconnect();
    activeSource = null;
  }

  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
}

export async function speakCoach(
  text: string,
  language: CoachLanguage,
): Promise<void> {
    const cleanText = text.trim();

    if (!cleanText) return;

    const spokenText =
    makeSpeechFriendly(
        cleanText,
        language,
    );

    stopCoachSpeech();

  const controller =
    new AbortController();

  activeRequest = controller;

  const startedAt =
    performance.now();

  try {
    console.log(
      '[TTS] Requesting ElevenLabs:',
      {
        language,
        text: cleanText,
      },
    );

    const response = await fetch(
      `${CONTROL_URL}/api/tts`,
      {
        method: 'POST',

        headers: {
          'Content-Type':
            'application/json',
        },

        body: JSON.stringify({
          text: spokenText,
          language,
        }),

        signal: controller.signal,
      },
    );

    const responseAt =
      performance.now();

    console.log(
      `[TTS] Backend responded in ${Math.round(
        responseAt - startedAt,
      )} ms`,
    );

    if (!response.ok) {
      const message =
        await response
          .text()
          .catch(() => '');

      throw new Error(
        `TTS backend ${response.status}: ${message}`,
      );
    }

    const audioBytes =
      await response.arrayBuffer();

    console.log(
      '[TTS] Received audio bytes:',
      audioBytes.byteLength,
    );

    activeRequest = null;

    /*
     * Use WebAudio rather than creating a new HTMLAudioElement
     * for every message.
     *
     * This is more reliable after iOS audio has been unlocked
     * by the Voice checkbox.
     */
    if (!audioContext) {
      audioContext =
        new AudioContext();
    }

    if (
      audioContext.state ===
      'suspended'
    ) {
      await audioContext.resume();
    }

    const decoded =
      await audioContext.decodeAudioData(
        audioBytes.slice(0),
      );

    const source =
      audioContext.createBufferSource();

    source.buffer = decoded;

    source.connect(
      audioContext.destination,
    );

    activeSource = source;

    source.onended = () => {
      if (activeSource === source) {
        activeSource = null;
      }

      source.disconnect();
    };

    console.log(
      `[TTS] Playing ElevenLabs after ${Math.round(
        performance.now() -
          startedAt,
      )} ms`,
    );

    source.start();
  } catch (error) {
    if (
      error instanceof DOMException &&
      error.name === 'AbortError'
    ) {
      return;
    }

    activeRequest = null;

    console.error(
      '[TTS] ElevenLabs failed:',
      error,
    );

    browserSpeak(
      spokenText,
      language,
    );
  }
}