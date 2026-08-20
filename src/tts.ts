import type { CoachLanguage } from './coach';

const CONTROL_URL =
  import.meta.env.VITE_BOT_CONTROL_URL ||
  'http://127.0.0.1:8765';

export type TtsStatus = {
  state:
    | 'checking'
    | 'ready'
    | 'online'
    | 'blocked'
    | 'offline';
  detail?: string;
};

let ttsStatus: TtsStatus = {
  state: 'checking',
};

const ttsStatusListeners = new Set<
  (status: TtsStatus) => void
>();

function publishTtsStatus(status: TtsStatus) {
  ttsStatus = status;

  for (const listener of ttsStatusListeners) {
    listener(status);
  }
}

export function subscribeTtsStatus(
  listener: (status: TtsStatus) => void,
): () => void {
  ttsStatusListeners.add(listener);
  listener(ttsStatus);

  return () => {
    ttsStatusListeners.delete(listener);
  };
}

export async function checkTtsStatus(): Promise<void> {
  publishTtsStatus({
    state: 'checking',
  });

  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    TTS_REQUEST_TIMEOUT_MS,
  );

  try {
    const response = await fetch(
      `${CONTROL_URL}/api/health`,
      {
        cache: 'no-store',
        signal: controller.signal,
      },
    );

    if (!response.ok) {
      throw new Error(
        `Voice server returned HTTP ${response.status}.`,
      );
    }

    const health = (await response.json()) as {
      tts?: {
        configured?: boolean;
        provider?: string;
      };
    };

    if (!health.tts?.configured) {
      publishTtsStatus({
        state: 'offline',
        detail: 'ElevenLabs is not configured on the server.',
      });
      return;
    }

    // Do not downgrade a real TTS result if the initial health check finishes
    // after the user has already tapped the voice test.
    if (
      ttsStatus.state !== 'online' &&
      ttsStatus.state !== 'blocked'
    ) {
      publishTtsStatus({
        state: 'ready',
        detail: 'ElevenLabs is configured. Tap to test playback.',
      });
    }
  } catch (error) {
    publishTtsStatus({
      state: 'offline',
      detail: `Voice status check failed: ${String(error)}`,
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

let activeRequest: AbortController | null = null;

let audioContext: AudioContext | null = null;
let activeSource: AudioBufferSourceNode | null = null;
let activeAudio: HTMLAudioElement | null = null;
let unlockedAudio: HTMLAudioElement | null = null;
let htmlAudioUnlocked = false;
let htmlAudioUnlocking = false;
let activeObjectUrl: string | null = null;
let activeAudioFinish: (() => void) | null = null;
let activeUtterance: SpeechSynthesisUtterance | null = null;

// Render can need well over 20 seconds to wake a sleeping service. A short
// timeout made a healthy ElevenLabs response look like a provider failure and
// immediately switched the user to the system/browser voice.
const TTS_REQUEST_TIMEOUT_MS = 60_000;

// A tiny valid WAV used only while the user is tapping the Voice control. It
// unlocks one reusable HTMLAudioElement for iOS/WKWebView; creating a brand-new
// element after an async TTS request can be rejected as autoplay.
const SILENT_WAV_DATA_URL =
  'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQIAAACAgA==';

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

    // iOS also uses a non-standard `interrupted` state after the app returns
    // from the background. resume() is safe for every non-running state.
    if (audioContext.state !== 'running') {
      await audioContext.resume();
    }

    // Starting a tiny silent buffer inside the user's gesture makes the
    // unlocked state stick much more reliably in iOS Safari/WKWebView.
    if (audioContext.state === 'running') {
      const silentBuffer = audioContext.createBuffer(1, 1, 22_050);
      const silentSource = audioContext.createBufferSource();
      silentSource.buffer = silentBuffer;
      silentSource.connect(audioContext.destination);
      silentSource.start();
    }

    if (!unlockedAudio) {
      unlockedAudio = new Audio();
      unlockedAudio.preload = 'auto';
      unlockedAudio.setAttribute('playsinline', 'true');
    }

    if (
      !htmlAudioUnlocked &&
      !htmlAudioUnlocking &&
      activeAudio !== unlockedAudio
    ) {
      const audio = unlockedAudio;
      htmlAudioUnlocking = true;
      audio.muted = true;
      audio.src = SILENT_WAV_DATA_URL;

      try {
        await audio.play();
        audio.pause();
        audio.currentTime = 0;
        htmlAudioUnlocked = true;
      } finally {
        audio.muted = false;
        htmlAudioUnlocking = false;
      }
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

  // Plain pawn move: e4 -> "E four". Without this branch ElevenLabs may
  // pronounce the square as a single token or as an unrelated word.
  if (/^[a-h][1-8]$/i.test(san)) {
    const destination = squareForSpeech(
      san,
      language,
    );

    return language === 'zh-CN'
      ? `兵走到${destination}${ending}`
      : `${destination}${ending}`;
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
    /(^|[^A-Za-z0-9])((?:O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h1-8]{0,2}x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?|[a-h][1-8]=[QRBN][+#]?|[a-h][1-8][+#]?))(?=$|[^A-Za-z0-9])/gi;

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

type SpeechJob = {
  text: string;
  language: CoachLanguage;
  resolve: () => void;
};

let speechQueue: SpeechJob[] = [];
let speechProcessing = false;
let speechGeneration = 0;

async function browserSpeak(
  text: string,
  language: CoachLanguage,
): Promise<void> {
  if (!('speechSynthesis' in window)) return;

  await new Promise<void>((resolve) => {
    const utterance =
      new SpeechSynthesisUtterance(text);

    // Safari can garbage-collect a locally scoped utterance before it ends.
    activeUtterance = utterance;

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
          ? voice.lang.toLowerCase().startsWith('zh')
          : voice.lang.toLowerCase().startsWith('en'),
      );

    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }

    let finished = false;

    const finish = () => {
      if (finished) return;
      finished = true;

      if (activeUtterance === utterance) {
        activeUtterance = null;
      }

      resolve();
    };

    utterance.onend = finish;
    utterance.onerror = finish;

    console.warn(
      '[TTS] Using browser fallback voice.',
    );

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(
      utterance,
    );

    window.setTimeout(
      finish,
      Math.min(
        15_000,
        Math.max(
          3_000,
          text.length * 85,
        ),
      ),
    );
  });
}

async function ensureAudioReady(): Promise<AudioContext> {
  if (
    !audioContext ||
    audioContext.state === 'closed'
  ) {
    audioContext =
      new AudioContext();
  }

  if (audioContext.state !== 'running') {
    await audioContext.resume();
  }

  if (audioContext.state !== 'running') {
    throw new Error(
      `WebAudio is ${audioContext.state}; tap the board once to enable sound.`,
    );
  }

  return audioContext;
}

async function playHtmlAudio(
  audioBytes: ArrayBuffer,
  generation: number,
): Promise<void> {
  if (generation !== speechGeneration) return;

  const objectUrl = URL.createObjectURL(
    new Blob([audioBytes], { type: 'audio/mpeg' }),
  );

  const audio = unlockedAudio || new Audio();
  unlockedAudio = audio;
  audio.src = objectUrl;
  audio.preload = 'auto';
  audio.muted = false;
  audio.setAttribute('playsinline', 'true');
  activeAudio = audio;
  activeObjectUrl = objectUrl;

  await new Promise<void>((resolve, reject) => {
    let finished = false;
    let playbackTimeout = 0;

    const cleanup = () => {
      window.clearTimeout(playbackTimeout);
      if (activeAudio === audio) activeAudio = null;
      if (activeObjectUrl === objectUrl) activeObjectUrl = null;
      if (activeAudioFinish === finish) activeAudioFinish = null;
      audio.onended = null;
      audio.onerror = null;
      URL.revokeObjectURL(objectUrl);
    };

    const finish = () => {
      if (finished) return;
      finished = true;
      cleanup();
      resolve();
    };

    const fail = () => {
      if (finished) return;
      finished = true;
      htmlAudioUnlocked = false;
      cleanup();
      reject(new Error('HTML audio playback failed.'));
    };

    audio.onended = finish;
    audio.onerror = fail;
    activeAudioFinish = finish;
    playbackTimeout = window.setTimeout(fail, 30_000);

    void audio.play().catch(fail);
  });
}

async function playWebAudio(
  audioBytes: ArrayBuffer,
  generation: number,
): Promise<void> {
  const context =
    await ensureAudioReady();

  if (
    generation !==
    speechGeneration
  ) {
    return;
  }

  const decoded =
    await context.decodeAudioData(
      audioBytes.slice(0),
    );

  if (
    generation !==
    speechGeneration
  ) {
    return;
  }

  await new Promise<void>((resolve) => {
    const source =
      context.createBufferSource();

    source.buffer = decoded;
    source.connect(
      context.destination,
    );

    activeSource = source;

    let finished = false;

    const finish = () => {
      if (finished) return;
      finished = true;

      if (
        activeSource === source
      ) {
        activeSource = null;
      }

      try {
        source.disconnect();
      } catch {
        // no-op
      }

      resolve();
    };

    source.onended = finish;
    source.start();

    window.setTimeout(
      finish,
      Math.ceil(
        decoded.duration * 1000,
      ) + 1500,
    );
  });
}

async function playSpeechJob(
  job: SpeechJob,
  generation: number,
): Promise<void> {
  const cleanText =
    job.text.trim();

  if (!cleanText) return;

  const spokenText =
    makeSpeechFriendly(
      cleanText,
      job.language,
    );

  const controller =
    new AbortController();

  let timedOut = false;

  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TTS_REQUEST_TIMEOUT_MS);

  activeRequest = controller;
  let providerResponded = false;
  const statusBeforeRequest = ttsStatus;

  publishTtsStatus({
    state: 'checking',
    detail: 'Requesting ElevenLabs audio…',
  });

  try {
    const response =
      await fetch(
        `${CONTROL_URL}/api/tts`,
        {
          method: 'POST',
          headers: {
            'Content-Type':
              'application/json',
          },
          body: JSON.stringify({
            text: spokenText,
            language:
              job.language,
          }),
          signal:
            controller.signal,
        },
      );

    if (
      activeRequest ===
      controller
    ) {
      activeRequest = null;
    }

    if (
      generation !==
      speechGeneration
    ) {
      return;
    }

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

    if (
      !audioBytes.byteLength
    ) {
      throw new Error(
        'TTS backend returned empty audio.',
      );
    }

    providerResponded = true;
    publishTtsStatus({
      state: 'online',
      detail: `ElevenLabs returned ${audioBytes.byteLength.toLocaleString()} bytes of audio.`,
    });

    try {
      await playWebAudio(
        audioBytes,
        generation,
      );
    } catch (webAudioError) {
      console.warn(
        '[TTS] WebAudio playback failed; trying HTML audio:',
        webAudioError,
      );

      await playHtmlAudio(
        audioBytes,
        generation,
      );
    }

  } catch (error) {
    if (
      error instanceof DOMException &&
      error.name === 'AbortError' &&
      !timedOut
    ) {
      publishTtsStatus(statusBeforeRequest);
      return;
    }

    console.error(
      '[TTS] ElevenLabs/WebAudio failed:',
      error,
    );

    publishTtsStatus(
      providerResponded
        ? {
            state: 'blocked',
            detail:
              'ElevenLabs returned audio, but this device could not play it. Tap the status to retry.',
          }
        : {
            state: 'offline',
            detail: `ElevenLabs request failed: ${String(error)}`,
          },
    );

    if (
      generation ===
      speechGeneration
    ) {
      await browserSpeak(
        spokenText,
        job.language,
      );
    }

  } finally {
    window.clearTimeout(timeout);

    if (
      activeRequest ===
      controller
    ) {
      activeRequest = null;
    }
  }
}

async function drainSpeechQueue(): Promise<void> {
  if (speechProcessing) return;

  speechProcessing = true;

  try {
    while (
      speechQueue.length > 0
    ) {
      const generation =
        speechGeneration;

      const job =
        speechQueue.shift();

      if (!job) continue;

      try {
        await playSpeechJob(
          job,
          generation,
        );
      } finally {
        job.resolve();
      }
    }

  } finally {
    speechProcessing = false;

    if (
      speechQueue.length > 0
    ) {
      void drainSpeechQueue();
    }
  }
}

export function stopCoachSpeech() {
  speechGeneration += 1;

  activeRequest?.abort();
  activeRequest = null;

  if (activeSource) {
    try {
      activeSource.stop();
    } catch {
      // no-op
    }

    try {
      activeSource.disconnect();
    } catch {
      // no-op
    }

    activeSource = null;
  }

  if (activeAudio) {
    activeAudio.pause();
    activeAudio.removeAttribute('src');
    activeAudio.load();
    activeAudio = null;
  }

  activeAudioFinish?.();
  activeAudioFinish = null;

  if (activeObjectUrl) {
    URL.revokeObjectURL(activeObjectUrl);
    activeObjectUrl = null;
  }

  if (
    'speechSynthesis'
    in window
  ) {
    window.speechSynthesis.cancel();
  }

  activeUtterance = null;

  const queued =
    speechQueue.splice(0);

  for (
    const job of queued
  ) {
    job.resolve();
  }
}

export async function speakCoach(
  text: string,
  language: CoachLanguage,
): Promise<void> {
  const cleanText =
    text.trim();

  if (!cleanText) return;

  const lastQueued =
    speechQueue.at(-1);

  if (
    lastQueued &&
    lastQueued.text ===
      cleanText &&
    lastQueued.language ===
      language
  ) {
    return;
  }

  await new Promise<void>(
    (resolve) => {
      speechQueue.push({
        text:
          cleanText,
        language,
        resolve,
      });

      while (
        speechQueue.length > 3
      ) {
        const dropped =
          speechQueue.shift();

        dropped?.resolve();
      }

      void drainSpeechQueue();
    },
  );
}
