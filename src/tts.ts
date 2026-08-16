import type { CoachLanguage } from './coach';

const CONTROL_URL =
  import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';

let activeAudio: HTMLAudioElement | null = null;
let activeObjectUrl: string | null = null;
let activeRequest: AbortController | null = null;

function browserSpeak(
  text: string,
  language: CoachLanguage,
) {
  if (!('speechSynthesis' in window)) return;

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);

  utterance.lang =
    language === 'zh-CN'
      ? 'zh-CN'
      : 'en-US';

  utterance.rate =
    language === 'zh-CN'
      ? 0.92
      : 0.96;

  const voices = window.speechSynthesis.getVoices();

  const preferredVoice = voices.find((voice) =>
    language === 'zh-CN'
      ? voice.lang.toLowerCase().startsWith('zh')
      : voice.lang.toLowerCase().startsWith('en'),
  );

  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }

  window.speechSynthesis.speak(utterance);
}

export function stopCoachSpeech() {
  activeRequest?.abort();
  activeRequest = null;

  if (activeAudio) {
    activeAudio.pause();
    activeAudio.src = '';
    activeAudio = null;
  }

  if (activeObjectUrl) {
    URL.revokeObjectURL(activeObjectUrl);
    activeObjectUrl = null;
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

  stopCoachSpeech();

  const controller = new AbortController();
  activeRequest = controller;

  try {
    const response = await fetch(
      `${CONTROL_URL}/api/tts`,
      {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json',
        },

        body: JSON.stringify({
          text: cleanText,
          language,
        }),

        signal: controller.signal,
      },
    );

    if (!response.ok) {
      throw new Error(
        `ElevenLabs TTS unavailable: ${response.status}`,
      );
    }

    const blob = await response.blob();

    if (!blob.size) {
      throw new Error('TTS returned empty audio.');
    }

    activeRequest = null;

    activeObjectUrl = URL.createObjectURL(blob);

    activeAudio = new Audio(activeObjectUrl);
    activeAudio.preload = 'auto';

    activeAudio.onended = () => {
      stopCoachSpeech();
    };

    activeAudio.onerror = () => {
      stopCoachSpeech();
    };

    await activeAudio.play();
  } catch (error) {
    if (
      error instanceof DOMException &&
      error.name === 'AbortError'
    ) {
      return;
    }

    activeRequest = null;

    if (activeObjectUrl) {
      URL.revokeObjectURL(activeObjectUrl);
      activeObjectUrl = null;
    }

    activeAudio = null;

    // Safety fallback:
    // if ElevenLabs is unavailable,
    // use the device/browser's built-in speech.
    browserSpeak(cleanText, language);
  }
}