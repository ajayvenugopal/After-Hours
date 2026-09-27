"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  MAX_AUDIO,
  MAX_TEXT,
  SAMPLE_TEXT,
  SECTIONS,
  exportNote,
  isNote,
  type Result,
  type Section,
} from "@/lib/notes";

type Mode = "sample" | "live";
type Status = "idle" | "recording" | "processing" | "requesting";
const sectionLabels: Record<Section, string> = {
  subjective: "Symptoms & history",
  objective: "Observations & findings",
  assessment: "Documented impression",
  plan: "Documented next steps",
};

export default function Workspace({
  liveAvailable,
}: {
  liveAvailable: boolean;
}) {
  const [mode, setMode] = useState<Mode>("sample");
  const [text, setText] = useState(SAMPLE_TEXT);
  const [token, setToken] = useState("");
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [seconds, setSeconds] = useState(0);
  const [tab, setTab] = useState<"text" | "audio">("text");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const request = useRef<AbortController | null>(null);
  const recordingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const generation = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = status !== "idle";
  const allowed =
    mode === "sample" || (liveAvailable && token.length >= 32 && consent);

  function releaseMicrophone() {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (recordingTimer.current) clearInterval(recordingTimer.current);
    recordingTimer.current = null;
  }
  function cancelWork() {
    generation.current++;
    request.current?.abort();
    request.current = null;
    if (recorder.current) {
      recorder.current.onstop = null;
      recorder.current.ondataavailable = null;
      if (recorder.current.state !== "inactive") recorder.current.stop();
    }
    recorder.current = null;
    releaseMicrophone();
  }
  useEffect(() => {
    // Remove data left by the pre-migration prototype; never persist new inputs.
    for (const key of ["clinicApiKey", "clinicEmail", "consultationData"]) {
      try {
        localStorage.removeItem(key);
      } catch {
        /* Storage may be disabled. */
      }
    }
    const lifecycle = generation;
    return () => {
      lifecycle.current++;
      request.current?.abort();
      if (recorder.current) {
        recorder.current.onstop = null;
        recorder.current.ondataavailable = null;
        if (recorder.current.state !== "inactive") recorder.current.stop();
      }
      stream.current?.getTracks().forEach((track) => track.stop());
      if (recordingTimer.current) clearInterval(recordingTimer.current);
    };
  }, []);

  function reset(nextMode = mode) {
    cancelWork();
    setMode(nextMode);
    setText(nextMode === "sample" ? SAMPLE_TEXT : "");
    setResult(null);
    setReviewed(false);
    setError("");
    setNotice("");
    setStatus("idle");
    setSeconds(0);
    setConsent(false);
    setToken("");
    setTab("text");
    if (fileInput.current) fileInput.current.value = "";
  }
  async function processInput(audio?: File | Blob) {
    if (!allowed) return;
    if (audio && audio.size > MAX_AUDIO) {
      setError("Audio must be 10 MB or smaller.");
      return;
    }
    const current = ++generation.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setStatus("processing");
    setError("");
    setNotice("");
    setReviewed(false);
    setResult(null);
    const headers: Record<string, string> = {};
    let body: BodyInit | undefined;
    if (mode === "sample") headers["x-gp-notes-demo"] = "true";
    else {
      headers.Authorization = `Bearer ${token}`;
      if (audio) {
        const form = new FormData();
        form.append(
          "audio",
          audio,
          audio.type.includes("mp4") ? "recording.mp4" : "recording.webm",
        );
        body = form;
      } else {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify({ text });
      }
    }
    const timeout = setTimeout(() => controller.abort(), 100_000);
    try {
      const response = await fetch(
        audio ? "/api/transcribe" : "/api/normalize-note",
        { method: "POST", headers, body, signal: controller.signal },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          typeof data.error === "string"
            ? data.error
            : "Unable to create a draft.",
        );
      if (
        !isNote(data.note) ||
        typeof data.transcription !== "string" ||
        !["sample", "live"].includes(data.source)
      )
        throw new Error("The server returned an invalid draft.");
      if (current !== generation.current) return;
      setResult(data);
      setText(data.transcription);
      setNotice(
        "Draft ready. Compare each section with the source before exporting.",
      );
    } catch (failure) {
      if (current === generation.current)
        setError(
          controller.signal.aborted
            ? "Request cancelled or timed out. Your source is still available."
            : failure instanceof Error
              ? failure.message
              : "Unable to connect. Please try again.",
        );
    } finally {
      clearTimeout(timeout);
      if (current === generation.current) {
        setStatus("idle");
        request.current = null;
      }
    }
  }
  async function startRecording() {
    if (!allowed || busy) return;
    setStatus("requesting");
    setError("");
    setNotice("");
    const current = ++generation.current;
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === "undefined"
      )
        throw new Error(
          "Recording needs a supported browser on localhost or HTTPS. You can also upload audio.",
        );
      const microphone = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      if (generation.current !== current) {
        microphone.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = microphone;
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(
        (value) => MediaRecorder.isTypeSupported(value),
      );
      if (!type)
        throw new Error(
          "This browser cannot record a supported format. Upload an audio file instead.",
        );
      const device = new MediaRecorder(microphone, { mimeType: type });
      recorder.current = device;
      const chunks: Blob[] = [];
      let bytes = 0;
      device.ondataavailable = (event) => {
        if (!event.data.size) return;
        bytes += event.data.size;
        chunks.push(event.data);
        if (bytes > MAX_AUDIO && device.state === "recording") device.stop();
      };
      device.onerror = () => {
        cancelWork();
        setStatus("idle");
        setError("Recording failed. Try uploading an audio file.");
      };
      device.onstop = () => {
        releaseMicrophone();
        recorder.current = null;
        if (generation.current !== current) return;
        setStatus("idle");
        const audio = new Blob(chunks, { type: device.mimeType });
        if (!audio.size) {
          setError("No audio captured. Try again.");
          return;
        }
        void processInput(audio);
      };
      device.start(1000);
      setSeconds(0);
      setStatus("recording");
      const start = Date.now();
      recordingTimer.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - start) / 1000);
        setSeconds(elapsed);
        if (elapsed >= 180 && device.state === "recording") device.stop();
      }, 1000);
    } catch (failure) {
      if (current === generation.current) {
        releaseMicrophone();
        setStatus("idle");
        setError(
          failure instanceof Error && failure.name === "NotAllowedError"
            ? "Microphone permission denied. Allow access or upload audio instead."
            : failure instanceof Error
              ? failure.message
              : "Unable to start recording.",
        );
      }
    }
  }
  function updateSection(section: Section, value: string) {
    setResult(
      (previous) =>
        previous && {
          ...previous,
          note: { ...previous.note, [section]: value },
        },
    );
    setReviewed(false);
    setNotice("");
  }
  async function copy() {
    if (!result || !reviewed) return;
    try {
      await navigator.clipboard.writeText(exportNote(result));
      setNotice("Reviewed draft copied to clipboard.");
    } catch {
      setError("Clipboard access unavailable. Download the draft instead.");
    }
  }
  function download() {
    if (!result || !reviewed) return;
    const url = URL.createObjectURL(
      new Blob([exportNote(result)], { type: "text/plain;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "gp-notes-reviewed-draft.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Reviewed draft downloaded.");
  }
  return (
    <div className="workspace">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="Gp Notes home">
          <span className="brand-mark" aria-hidden="true">
            ＋
          </span>
          <span>
            Gp Notes <small>by Afterhours</small>
          </span>
        </Link>
        <div className="header-meta">
          <span className="pill">DOCUMENTATION LAB</span>
          <button className="text-button" onClick={() => reset()}>
            Clear session ↗
          </button>
        </div>
      </header>
      <main id="main">
        <section className="hero">
          <div>
            <p className="eyebrow">LESS FORMATTING. MORE CONTEXT.</p>
            <h1>
              From conversation
              <br />
              to a considered draft<span>.</span>
            </h1>
            <p className="lede">
              Organize a consultation into clear SOAP notes.
              <br className="desktop-break" /> Keep the source close. Review
              every word.
            </p>
          </div>
          <aside className="hero-note">
            <span className="note-line" />{" "}
            <p>
              Built for exploration.
              <br />
              <strong>Designed for review.</strong>
            </p>
            <small>
              Use synthetic examples only.
              <br />
              Not a clinical record system.
            </small>
          </aside>
        </section>
        <div className="mode-bar">
          <div className="segmented" aria-label="Workspace mode">
            <button
              aria-pressed={mode === "sample"}
              onClick={() => reset("sample")}
              disabled={busy}
            >
              Sample demo
            </button>
            <button
              aria-pressed={mode === "live"}
              onClick={() => reset("live")}
              disabled={busy}
            >
              Live workspace
            </button>
          </div>
          <span className="mode-caption">
            <span className={`dot ${mode}`} />
            {mode === "sample"
              ? "Fixed example · no API key or provider calls"
              : "Your input is sent to OpenAI for processing"}
          </span>
        </div>
        {mode === "live" && (
          <section className="connection" aria-label="Live configuration">
            {liveAvailable ? (
              <>
                <div>
                  <label htmlFor="token">Workspace access token</label>
                  <input
                    id="token"
                    type="password"
                    autoComplete="off"
                    value={token}
                    onChange={(event) => setToken(event.target.value)}
                    placeholder="Enter the token configured by the server owner"
                    disabled={busy}
                  />
                  <small>
                    Held in memory for this session. This is not your OpenAI API
                    key.
                  </small>
                </div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(event) => setConsent(event.target.checked)}
                    disabled={busy}
                  />
                  <span>
                    I’m using synthetic content and agree to send it to OpenAI
                    for processing.
                  </span>
                </label>
              </>
            ) : (
              <p>
                <strong>Live mode is not configured.</strong> The sample is
                ready to explore. To enable live input, follow the project
                README and configure the server’s provider key and workspace
                access token.
              </p>
            )}
          </section>
        )}
        <div className="editor-grid">
          <section
            className="panel source-panel"
            aria-labelledby="source-heading"
          >
            <div className="panel-heading">
              <div>
                <p className="step">01 / SOURCE</p>
                <h2 id="source-heading">The consultation</h2>
              </div>
              <span className="mini-tag">
                {mode === "sample" ? "SYNTHETIC" : "SESSION ONLY"}
              </span>
            </div>
            <div className="input-tabs">
              <button
                aria-pressed={tab === "text"}
                onClick={() => setTab("text")}
                disabled={busy}
              >
                Written notes
              </button>
              <button
                aria-pressed={tab === "audio"}
                onClick={() => setTab("audio")}
                disabled={busy || mode === "sample"}
              >
                Voice & audio
              </button>
            </div>
            {tab === "text" ? (
              <>
                <label className="sr-only" htmlFor="source">
                  Source consultation
                </label>
                <textarea
                  id="source"
                  className="source-input"
                  value={text}
                  readOnly={mode === "sample"}
                  disabled={busy}
                  maxLength={MAX_TEXT}
                  placeholder="Paste a synthetic consultation. Include only what was said or observed…"
                  onChange={(event) => {
                    setText(event.target.value);
                    setResult(null);
                    setReviewed(false);
                    setNotice("");
                  }}
                />
                <div className="source-meta">
                  <span>
                    {mode === "sample"
                      ? "A fixed example, not a live AI response"
                      : "Missing details stay missing"}
                  </span>
                  <span>{text.length.toLocaleString()} / 20,000</span>
                </div>
              </>
            ) : (
              <div className="audio-input">
                <div
                  className={`record-disc ${status === "recording" ? "active" : ""}`}
                  aria-hidden="true"
                >
                  {status === "recording" ? "■" : "◉"}
                </div>
                <h3>
                  {status === "recording"
                    ? `Recording ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
                    : "Speak the source"}
                </h3>
                <p>
                  Up to 3 minutes of recording or a 10 MB upload.
                  <br />
                  WebM, MP4/M4A, MP3, or WAV.
                </p>
                {status === "recording" ? (
                  <button
                    className="primary"
                    onClick={() => recorder.current?.stop()}
                  >
                    Stop & create draft
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={!allowed || busy}
                    onClick={startRecording}
                  >
                    {status === "requesting"
                      ? "Waiting for microphone…"
                      : "Start recording"}
                  </button>
                )}
                <label className="upload-label">
                  Or upload an audio file
                  <input
                    ref={fileInput}
                    aria-label="Upload audio"
                    type="file"
                    accept="audio/webm,audio/mp4,audio/mpeg,audio/wav,audio/x-m4a,.m4a"
                    disabled={!allowed || busy}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void processInput(file);
                      event.target.value = "";
                    }}
                  />
                </label>
              </div>
            )}
            <div className="source-footer">
              {tab === "text" && (
                <button
                  className="primary generate"
                  onClick={() => processInput()}
                  disabled={busy || !allowed || !text.trim()}
                >
                  {status === "processing"
                    ? "Preparing your draft…"
                    : mode === "sample"
                      ? "Explore sample draft"
                      : "Create SOAP draft"}
                  <span aria-hidden="true">↗</span>
                </button>
              )}
              {busy && (
                <button
                  className="text-button"
                  onClick={() => {
                    cancelWork();
                    setStatus("idle");
                    setNotice("Cancelled. No draft was saved.");
                  }}
                >
                  Cancel
                </button>
              )}
              <p>Refresh or clear the session to discard inputs and drafts.</p>
            </div>
          </section>
          <section
            className="panel draft-panel"
            aria-labelledby="draft-heading"
            aria-busy={status === "processing"}
          >
            <div className="panel-heading">
              <div>
                <p className="step">02 / REVIEW</p>
                <h2 id="draft-heading">The structured draft</h2>
              </div>
              <span className={`mini-tag ${reviewed ? "reviewed" : ""}`}>
                {reviewed ? "REVIEWED" : result ? "NEEDS REVIEW" : "SOAP"}
              </span>
            </div>
            {!result ? (
              <div className="empty-draft">
                <div className="document-glyph" aria-hidden="true">
                  <span>S</span>
                  <i />
                  <span>O</span>
                  <i />
                  <span>A</span>
                  <i />
                  <span>P</span>
                  <i />
                </div>
                <h3>
                  {status === "processing"
                    ? "Organizing the source…"
                    : "A little structure. A clearer note."}
                </h3>
                <p>
                  {status === "processing"
                    ? "Your draft will appear here. You can cancel at any time."
                    : "Generate a draft to see the source organized into four sections. Nothing is exported until you review it."}
                </p>
                <div className="section-chips">
                  {SECTIONS.map((key) => (
                    <span key={key}>{key}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="draft-content">
                {result.source === "sample" && (
                  <p className="sample-banner">
                    SYNTHETIC SAMPLE · Prepared example, not generated AI output
                  </p>
                )}
                {SECTIONS.map((key, index) => (
                  <div className="soap-section" key={key}>
                    <div className="soap-label">
                      <span className="soap-letter">
                        {key[0].toUpperCase()}
                      </span>
                      <div>
                        <label htmlFor={key}>{key}</label>
                        <small>{sectionLabels[key]}</small>
                      </div>
                      <span className="section-number">0{index + 1}</span>
                    </div>
                    <textarea
                      id={key}
                      value={result.note[key]}
                      maxLength={MAX_TEXT}
                      onChange={(event) =>
                        updateSection(key, event.target.value)
                      }
                      rows={3}
                    />
                  </div>
                ))}
                <aside className="review-notes">
                  <h3>Check against the source</h3>
                  {result.note.reviewNotes.length ? (
                    <ul>
                      {result.note.reviewNotes.map((note, index) => (
                        <li key={index}>{note}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>
                      No specific ambiguities flagged. Verify all sections
                      anyway.
                    </p>
                  )}
                </aside>
                <label className="check review-check">
                  <input
                    type="checkbox"
                    checked={reviewed}
                    onChange={(event) => setReviewed(event.target.checked)}
                  />
                  <span>
                    I have compared this draft with the source and reviewed my
                    edits.
                  </span>
                </label>
                <div className="export-actions">
                  <button
                    className="primary"
                    disabled={!reviewed}
                    onClick={copy}
                  >
                    Copy note
                  </button>
                  <button
                    className="secondary"
                    disabled={!reviewed}
                    onClick={download}
                  >
                    Download .txt
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
        <div className="feedback" aria-live="polite">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
        </div>
        <section className="principles" aria-label="How it works">
          <div>
            <span>01</span>
            <h3>Source first</h3>
            <p>
              The original words stay beside the draft so you can check context
              and omissions.
            </p>
          </div>
          <div>
            <span>02</span>
            <h3>You stay the editor</h3>
            <p>
              Edit any SOAP section. Every change resets review before you copy
              or download.
            </p>
          </div>
          <div>
            <span>03</span>
            <h3>No saved sessions</h3>
            <p>
              The app keeps inputs in memory. Live processing uses OpenAI;
              provider policies apply.
            </p>
          </div>
        </section>
      </main>
      <footer>
        <span>Gp Notes / An Afterhours experiment</span>
        <span>
          Documentation assistance, not diagnosis or treatment advice.
        </span>
      </footer>
    </div>
  );
}
