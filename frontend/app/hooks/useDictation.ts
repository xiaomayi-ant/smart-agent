'use client';

import { useCallback, useRef, useState } from 'react';

export type DictationResult = { text: string; blob: Blob; audioId?: string; url?: string };

export function useDictation() {
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeCandidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/wav',
    ];
    const mimeType = mimeCandidates.find((t) => MediaRecorder.isTypeSupported?.(t)) || 'audio/webm';
    const mr = new MediaRecorder(stream, { mimeType });
    chunksRef.current = [];
    mr.ondataavailable = (e) => e.data && e.data.size && chunksRef.current.push(e.data);
    mediaRecorderRef.current = mr;
    mr.start();
    setIsRecording(true);
  }, []);

  const stop = useCallback(async (): Promise<DictationResult | null> => {
    const mr = mediaRecorderRef.current;
    if (!mr) return null;
    setIsBusy(true);
    const result = await new Promise<DictationResult | null>((resolve) => {
      const onStop = async () => {
        try {
          const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
          const form = new FormData();
          form.append('file', blob, `recording-${Date.now()}.webm`);
          const res = await fetch('/api/transcribe', { method: 'POST', body: form });
          if (!res.ok) throw new Error('transcribe_failed');
          const json = await res.json();
          resolve({ text: String(json?.text || ''), blob, audioId: json?.audioId, url: json?.url });
        } catch (e) {
          console.error('dictation stop error', e);
          resolve(null);
        } finally {
          try { mr.stream.getTracks().forEach((t) => t.stop()); } catch {}
          setIsBusy(false);
          setIsRecording(false);
          mediaRecorderRef.current = null;
          chunksRef.current = [];
        }
      };
      mr.addEventListener('stop', onStop, { once: true });
      try { mr.stop(); } catch { onStop(); }
    });
    return result;
  }, []);

  return { isRecording, isBusy, start, stop };
}


