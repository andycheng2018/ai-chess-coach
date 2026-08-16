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

  if (!cleanText) {
    return;
  }

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
          text: cleanText,
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
      cleanText,
      language,
    );
  }
}