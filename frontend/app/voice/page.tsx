"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, X } from "lucide-react";

type ServerEvent = { type: string; [k: string]: any };

export default function VoicePage() {
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "error" | "closed">("idle");
  const [error, setError] = useState<string>("");
  const [vadState, setVadState] = useState<"silent" | "speaking" | "">("");
  const [isMuted, setIsMuted] = useState<boolean>(false);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const startedRef = useRef<boolean>(false);

  useEffect(() => {
    // 进入页面即尝试鉴权并自动连接
    (async () => {
      try {
        if (startedRef.current) return;
        startedRef.current = true;
        setStatus("connecting");
        // 兜底设置 sid（无论是否已有都会刷新）
        try { await fetch('/api/auth/guest', { credentials: 'include' }); } catch {}
        await connect();
      } catch (e: any) {
        setError(e?.message || "连接失败");
        setStatus("error");
      }
    })();
    return () => { try { stop(); } catch {} };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function connect() {
    const tokenResp = await fetch("/api/voice/token");
    if (!tokenResp.ok) throw new Error(`获取临时凭证失败: ${tokenResp.status}`);
    const { client_secret } = await tokenResp.json();

    const local = await navigator.mediaDevices.getUserMedia({ audio: true });
    localStreamRef.current = local;

    const pc = new RTCPeerConnection();
    pcRef.current = pc;

    pc.ontrack = (e) => {
      const [stream] = e.streams;
      if (remoteAudioRef.current) {
        remoteAudioRef.current.srcObject = stream;
        try { remoteAudioRef.current.play().catch(() => {}); } catch {}
      }
    };

    const [track] = local.getAudioTracks();
    pc.addTrack(track, local);

    const dc = pc.createDataChannel("oai-events");
    dcRef.current = dc;

    dc.onopen = () => {
      const evt = {
        type: "session.update",
        session: {
          type: "realtime",
          model: "gpt-realtime",
          output_modalities: ["audio", "text"],
          audio: {
            input: { format: { type: "audio/pcm", rate: 24000 }, turn_detection: { type: "semantic_vad" } },
            output: { format: { type: "audio/pcm" }, voice: "alloy" },
          },
          instructions: "请用中文、简洁、清晰地与我对话。",
        },
      };
      try { dc.send(JSON.stringify(evt)); } catch {}
    };

    dc.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as ServerEvent;
        if (msg.type === "input_audio_buffer.speech_started") setVadState("speaking");
        else if (msg.type === "input_audio_buffer.speech_stopped") setVadState("silent");
      } catch {}
    };

    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);

    const sdpResp = await fetch("https://api.openai.com/v1/realtime?model=gpt-realtime", {
      method: "POST",
      headers: { Authorization: `Bearer ${client_secret}`, "Content-Type": "application/sdp" },
      body: offer.sdp || "",
    });
    if (!sdpResp.ok) throw new Error(`SDP 交换失败: ${sdpResp.status}`);
    const answer = { type: "answer", sdp: await sdpResp.text() } as RTCSessionDescriptionInit;
    await pc.setRemoteDescription(answer);

    pc.onconnectionstatechange = () => {
      const st = pc.connectionState;
      if (st === "connected") setStatus("connected");
      else if (st === "connecting") setStatus("connecting");
      else if (st === "disconnected" || st === "failed" || st === "closed") setStatus("closed");
    };

    setStatus("connected");
    setIsMuted(false);
  }

  function stop() {
    try { dcRef.current?.close(); } catch {}
    try { pcRef.current?.close(); } catch {}
    try { localStreamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
    pcRef.current = null;
    dcRef.current = null;
    localStreamRef.current = null;
    setStatus("closed");
    setVadState("");
  }

  async function onMicClick() {
    try {
      if (!pcRef.current) {
        setStatus("connecting");
        await connect();
        return;
      }
      const track = localStreamRef.current?.getAudioTracks()?.[0];
      if (track) {
        const next = !track.enabled;
        track.enabled = next;
        setIsMuted(!next);
      }
    } catch (e: any) {
      setError(e?.message || "连接失败");
      setStatus("error");
    }
  }

  function onExit() {
    try { stop(); } catch {}
    try {
      if (window.history.length > 1) window.history.back(); else window.location.assign("/");
    } catch {}
  }

  const circleClass = `
    w-48 h-48 md:w-56 md:h-56 rounded-full
    bg-gradient-to-b from-sky-100 to-sky-400
    drop-shadow-md transform -translate-y-[10vh]
  `;

  return (
    <div className="fixed inset-0 z-[100] bg-background flex flex-col items-center justify-center select-none">
      <audio ref={remoteAudioRef} autoPlay playsInline />

      <div className={circleClass} />

      {/* Controls */}
      <div className="fixed bottom-10 left-0 right-0 flex items-center justify-center gap-8">
        <button
          type="button"
          aria-label="mic"
          onClick={onMicClick}
          className="w-14 h-14 rounded-full bg-white shadow-md flex items-center justify-center hover:shadow-lg transition-shadow"
        >
          <Mic className={`w-6 h-6 ${isMuted ? 'text-gray-400' : 'text-black'}`} />
        </button>
        <button
          type="button"
          aria-label="exit"
          onClick={onExit}
          className="w-14 h-14 rounded-full bg-white shadow-md flex items-center justify-center hover:shadow-lg transition-shadow"
        >
          <X className="w-6 h-6" />
        </button>
      </div>

      {/* Optional lightweight error indicator (no verbose text) */}
      {error ? <div className="fixed top-4 text-sm text-red-500">{error}</div> : null}
    </div>
  );
}


