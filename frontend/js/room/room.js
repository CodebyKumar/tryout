// Candidate interview, video-call style: lobby (checks, resume, consent) -> call -> finished.
// Turn-taking: the interviewer speaks (Deepgram audio, or the browser's own voice) -> we listen with voice-activity
// detection -> the answer is transcribed by Whisper on the server -> next question. Typing is always available.
import { api, postForm } from "../lib/api.js";
import { $, LOGO, confirmDialog, esc, fmt, when } from "../lib/ui.js";
import { checkExtensions, enterFullscreen, startMonitor } from "./integrity.js";

const token = location.pathname.split("/").pop();
const st = { info: null, view: null, syncedAt: 0, phase: "idle", micOn: true, camOn: false, cc: true, resumeOk: false, extensions: [], paused: false };
document.querySelectorAll("[data-brand]").forEach((b) => (b.innerHTML = `${LOGO}<span>TryOut</span>`));
let stream = null, audioCtx = null, analyser = null, recorder = null, vadRaf = null, agentAudio = null, micSource = null;

// Phones switch to earpiece ("call mode") while a page holds the microphone. On mobile we release the mic as soon as
// an answer is sent and reopen it after the interviewer finishes. The phone needs about a second to move audio back to
// the loudspeaker, and that switch must never happen while the interviewer is talking, or words drop out.
const ROUTE_SETTLE_MS = 1200;
let micReleasedAt = 0;
const MOBILE = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform));
const AUDIO = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };

function audioSession(type) {
  try { if (navigator.audioSession) navigator.audioSession.type = type; } catch {}
}

function releaseMic() {
  if (!MOBILE || !stream) return;
  micSource?.disconnect(); micSource = null;
  if (!stream.getAudioTracks().length) return;
  stream.getAudioTracks().forEach((t) => { t.stop(); stream.removeTrack(t); });
  micReleasedAt = Date.now();
  audioSession("playback");
}

async function acquireMic() {
  if (!stream) stream = new MediaStream();
  if (stream.getAudioTracks().length) return true;
  try {
    const mic = await navigator.mediaDevices.getUserMedia({ audio: AUDIO });
    mic.getAudioTracks().forEach((t) => { t.enabled = st.micOn; stream.addTrack(t); });
    if (audioCtx) { micSource = audioCtx.createMediaStreamSource(stream); micSource.connect(analyser); }
    audioSession("play-and-record");
    return true;
  } catch { return false; }
}

const show = (id) => ["prejoin", "call", "finished", "invalid", "waiting"].forEach((v) => $(`#${v}`).classList.toggle("hidden", v !== id));
const invalid = (title, msg) => { $("#invalidTitle").textContent = title; $("#invalidMsg").textContent = msg; show("invalid"); };
const live = () => ["INTERVIEWING", "WRAPUP"].includes(st.view?.state);

// ---------- Pre-join ----------
async function init() {
  try { st.info = await api(`/i/${token}`); }
  catch (e) { return invalid("This link isn’t valid", e.status === 404 ? "Check that you opened the full link from your invite. If the recruiter reset your interview, they sent you a new one." : e.message); }
  const info = st.info;
  if (info.interview) {
    st.view = info.interview;
    if (!live()) return finished();
  } else {
    // The server's clock decides when the window opens, not the device's.
    const skew = new Date(info.server_time) - Date.now();
    if (info.closes_at && new Date(info.closes_at) - skew < Date.now()) return invalid("This interview link has expired", "Ask the recruiter for a new link.");
    if (info.opens_at && new Date(info.opens_at) - skew > Date.now()) return waitForOpening(info, skew);
  }
  st.resumeOk = info.has_resume || !!info.interview;
  $("#pjTitle").textContent = info.interview ? "Rejoin your interview" : `Hi ${info.name.split(" ")[0]}, ready to join?`;
  const item = (k, v) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`;
  $("#pjMeta").innerHTML = item("Role", info.role_title) + (info.company ? item("Company", info.company) : "") + item("Length", `About ${info.minutes} min`);
  $("#resumeBox").classList.toggle("hidden", st.resumeOk);
  $("#consentText").textContent = `I agree to an interview led by an AI interviewer. My answers are transcribed and shared with the hiring team. My camera stays on this device and is not recorded. ${info.strict
    ? "This interview runs in full screen; copying, pasting and right-click are turned off, and leaving full screen pauses it. Leaving the tab and browser extensions are noted for the hiring team."
    : "Leaving the tab or full screen, copying or pasting, and browser extensions are noted for the hiring team."}`;
  show("prejoin");
  runChecks(openDevices()); // the microphone prompt can wait on the candidate; the other checks don't
}

// A scheduled interview that has not opened yet: count down, then show the lobby.
function waitForOpening(info, skew) {
  show("waiting");
  $("#waitMsg").textContent = `Your ${info.role_title} interview opens ${when(info.opens_at)}. Keep this page open; the lobby opens by itself at that time.`;
  const tick = setInterval(() => {
    const left = (new Date(info.opens_at) - skew - Date.now()) / 1000;
    if (left <= 0) { clearInterval(tick); location.reload(); return; }
    $("#waitClock").textContent = left > 3600 ? `${Math.floor(left / 3600)} h ${Math.floor((left % 3600) / 60)} min` : fmt(left);
  }, 1000);
}

// What the lobby checks, shown as a list. In strict mode a detected extension stops the join button.
async function runChecks(devices) {
  const strict = st.info.strict;
  st.checksOk = false; // Join waits for the extension check
  const draw = () => ($("#checks").innerHTML = rows.map(([ok, text]) => `<li class="${ok === null ? "" : ok ? "ok" : "bad"}"><span class="dot" aria-hidden="true"></span>${esc(text)}</li>`).join(""));
  const rows = [[null, "Waiting for microphone permission..."], [null, "Checking browser extensions..."]];
  if (strict) rows.push([null, "Full screen starts when you join"]);
  if (strict && MOBILE) rows.push([false, "This interview needs a computer: phones can't hold full screen"]);
  draw();
  devices.then(() => {
    const mic = !!stream?.getAudioTracks().length;
    rows[0] = [mic, mic ? "Microphone works" : "No microphone: you can type your answers instead"];
    draw();
  });
  st.extensions = await checkExtensions();
  rows[1] = st.extensions.length
    ? [!strict, `${strict ? "Turn off for this site, then reload" : "Extensions noted for the hiring team"}: ${st.extensions.join(", ")}`]
    : [true, "No extensions detected (a page can't see every kind)"];
  draw();
  st.checksOk = !(strict && (st.extensions.length || MOBILE));
  updateJoin();
}

async function openDevices() {
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  // Camera is off by default and only requested when the candidate turns it on.
  try { stream = await navigator.mediaDevices.getUserMedia({ audio }); }
  catch { return; } // the lobby's check list says so, and typing still works
  $("#preview").srcObject = stream;
  setCam(false);
  audioCtx = new AudioContext();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  micSource = audioCtx.createMediaStreamSource(stream);
  micSource.connect(analyser);
  const meter = () => { $("#meterBar").style.width = `${Math.min(100, level() * 900)}%`; if (!$("#prejoin").classList.contains("hidden")) requestAnimationFrame(meter); };
  meter();
}

function level() {
  if (!analyser) return 0;
  const buf = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(buf);
  let sum = 0; for (const v of buf) sum += v * v;
  return Math.sqrt(sum / buf.length);
}

function updateJoin() { $("#joinBtn").disabled = !($("#consent").checked && st.resumeOk && st.checksOk !== false); }
$("#consent").addEventListener("change", updateJoin);

async function uploadResume(file) {
  const fd = new FormData();
  fd.append("file", file);
  $("#resumeLabel").textContent = file.name;
  const stop = resumeLoader();
  try {
    await postForm(`/i/${token}/resume`, fd);
    stop();
    st.resumeOk = true;
    $("#resumeBox").classList.add("done");
    $("#resumeStatus").textContent = "Resume read. Your interview is ready.";
    updateJoin();
  } catch (err) {
    stop();
    $("#resumeStatus").textContent = `${err.message} Choose another file to try again.`;
    $("#resumeLabel").textContent = "Choose a file or drop it here";
    $("#resumeFile").value = "";
  }
}
// Loader while the resume is read: the steps reflect what the server does (upload, read, prepare questions).
function resumeLoader() {
  const steps = [[0, "Uploading your resume"], [1.5, "Reading your experience and projects"], [4, "Preparing questions about your work"], [9, "Almost ready"]];
  const t0 = Date.now();
  $("#resumeStatus").textContent = "";
  $("#resumeProgress").classList.remove("hidden");
  document.querySelector(".file-btn").classList.add("busy");
  const draw = () => {
    const s = (Date.now() - t0) / 1000;
    $("#resumeStep").textContent = steps.filter(([at]) => s >= at).at(-1)[1];
    $("#resumeTime").textContent = ` ${Math.floor(s)}s`;
    $("#resumeBar").style.width = `${Math.min(92, 100 * (1 - Math.exp(-s / 5)))}%`; // eases toward done, never fakes 100%
  };
  draw();
  const id = setInterval(draw, 250);
  return () => {
    clearInterval(id);
    $("#resumeProgress").classList.add("hidden");
    document.querySelector(".file-btn").classList.remove("busy");
  };
}

$("#resumeFile").addEventListener("change", () => { const f = $("#resumeFile").files[0]; if (f) uploadResume(f); });
// Drag and drop onto the upload box, the same as choosing the file.
const drop = $("#dropZone");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer.files[0]; if (f) uploadResume(f); });

$("#joinBtn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#pjStatus").textContent = "Connecting...";
  try {
    await audioCtx?.resume();
    const full = await enterFullscreen(); // from the click, so the browser allows it; standard mode can decline
    if (st.info.strict && !full) throw new Error("This interview runs in full screen. Allow full screen and press Join again.");
    releaseMic(); // let the phone settle on the loudspeaker while the interview loads
    st.view = await api(`/i/${token}/start`, { method: "POST", body: { extensions: st.extensions, fullscreen: full } });
    enterCall();
    startIntegrity();
  } catch (err) {
    $("#pjStatus").textContent = err.status === 503 ? `${err.message} The page will try again when you press Join.` : err.message;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    e.target.disabled = false;
  }
});

// ---------- Call ----------
function enterCall() {
  show("call");
  const name = st.info.name;
  $("#callTitle").textContent = `${st.info.role_title} interview`;
  $("#meName").textContent = name;
  $("#meInitials").textContent = name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  setCam(st.camOn);
  if (!stream) { st.micOn = false; toggleType(true); }
  setView(st.view);
  const last = st.view.turns.at(-1);
  if (last.role === "agent") speakTurn(last);
  else listen();
}

// Browser signals for the recruiter's report (tab switches, leaving full screen, paste). Context only, never scored.
let stopMonitor = null, noticeTimer = null;
function startIntegrity() {
  stopMonitor?.();
  stopMonitor = startMonitor({
    clock: () => st.view.elapsed_sec + (Date.now() - st.syncedAt) / 1000,
    send: (events, keepalive) => fetch(`/api/i/${token}/events`, { method: "POST", keepalive, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events }) }),
    notify: (msg) => { $("#notice").textContent = msg; $("#notice").classList.remove("hidden"); clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $("#notice").classList.add("hidden"), 6000); },
    strict: st.info.strict,
    onFullscreen: (full) => st.info.strict && pause(!full),
  });
}

// Strict mode: leaving full screen pauses the interview (no listening, no speaking) until the candidate returns.
function pause(on) {
  if (!live() || on === st.paused) return;
  st.paused = on;
  $("#paused").classList.toggle("hidden", !on);
  if (on) { stopRecording(false); agentAudio?.pause(); speechSynthesis?.cancel(); stopVoice(); setPhase("idle"); }
  else listen();
}
$("#resumeFull").addEventListener("click", () => enterFullscreen());

function setView(v) { st.view = v; st.syncedAt = Date.now(); drawParts(); }

// Where the candidate is in the interview: one segment per part, never coverage or scores.
function drawParts() {
  const parts = st.view?.sections || [];
  const now = parts.findIndex((p) => p.section_id === st.view.current_section_id);
  if (!parts.length || now < 0) return ($("#parts").innerHTML = "");
  $("#parts").innerHTML = `<span class="part-label">Part ${now + 1} of ${parts.length}: ${esc(parts[now].name)}</span>
    <span class="part-bar" aria-hidden="true">${parts.map((p, i) => `<i class="${i < now || ["satisfied", "partial", "skipped"].includes(p.status) ? "done" : i === now ? "now" : ""}"></i>`).join("")}</span>`;
}

// Countdown the candidate can always see. Server time is authoritative; we extrapolate between turns.
setInterval(() => {
  if (!live()) return;
  const left = st.view.time_budget_sec - (st.view.elapsed_sec + (Date.now() - st.syncedAt) / 1000);
  $("#timer").textContent = left > 0 ? `${fmt(left)} left` : "Wrapping up";
  $("#timer").classList.toggle("low", left <= 60);
  $("#timer").classList.toggle("over", left <= 0);
}, 500);

function caption(who, text) {
  $("#captions").innerHTML = text ? `<span class="who">${esc(who)}</span>${esc(text)}` : "";
}

function setPhase(p) {
  st.phase = p;
  $("#aiTile").classList.toggle("speaking", p === "speaking");
  $("#thinking").classList.toggle("hidden", p !== "thinking");
  $("#doneBtn").disabled = p !== "listening";
  $("#micState").textContent = !st.micOn ? "Muted" : p === "listening" ? "Listening" : "";
}

// The interviewer tile's bars follow the real voice level of the audio being played.
let voiceRaf = null;
const bars = () => [...document.querySelectorAll("#voice i")];
function animateVoice(an) {
  cancelAnimationFrame(voiceRaf);
  const data = an ? new Uint8Array(an.frequencyBinCount) : null;
  const step = (t) => {
    bars().forEach((b, i) => {
      let v;
      if (data) { an.getByteFrequencyData(data); v = data[3 + i * 4] / 255; }
      else v = 0.35 + 0.35 * Math.sin(t / 140 + i * 1.3) * Math.sin(t / 310 + i);
      b.style.height = `${8 + Math.max(0, v) * 52}px`;
    });
    voiceRaf = requestAnimationFrame(step);
  };
  voiceRaf = requestAnimationFrame(step);
}
function stopVoice() { cancelAnimationFrame(voiceRaf); bars().forEach((b) => (b.style.height = "8px")); }

function speakTurn(turn) {
  stopRecording(false);
  releaseMic(); // normally already released when the answer was sent
  setPhase("speaking");
  caption("Interviewer", turn.text);
  const after = () => { stopVoice(); agentAudio = null; if (live()) listen(); else finished(); };
  if (!st.info.voice) return browserVoice(turn.text, after); // no voice service configured: skip the request
  agentAudio = new Audio(`/api/i/${token}/tts/${turn.turn_id}`);
  if (audioCtx) {
    const an = audioCtx.createAnalyser();
    an.fftSize = 64;
    audioCtx.createMediaElementSource(agentAudio).connect(an);
    an.connect(audioCtx.destination);
    agentAudio.onplay = () => animateVoice(an);
  } else agentAudio.onplay = () => animateVoice(null);
  agentAudio.onended = after;
  agentAudio.onerror = () => browserVoice(turn.text, after);
  const audio = agentAudio;
  // Start only once the phone has finished moving audio to the loudspeaker (usually already true after "thinking").
  const wait = MOBILE ? Math.max(0, ROUTE_SETTLE_MS - (Date.now() - micReleasedAt)) : 0;
  setTimeout(() => audio.play().catch(() => browserVoice(turn.text, after)), wait);
}

function browserVoice(text, after) {
  // When the voice service is off or fails: the browser's own voice (it differs by browser and system).
  if (!window.speechSynthesis) return after();
  const u = new SpeechSynthesisUtterance(text);
  animateVoice(null);
  u.onend = after; u.onerror = after;
  speechSynthesis.speak(u);
}

// ---------- Listening with voice-activity detection ----------
function listen() {
  if (MOBILE && st.micOn && live() && !stream?.getAudioTracks().length) {
    acquireMic().then((ok) => ok ? listen() : (caption("", "Microphone unavailable. Use Type to answer."), setPhase("idle")));
    return;
  }
  if (!live() || st.paused) return;
  if (!st.micOn || !stream) return setPhase("idle");
  setPhase("listening");
  const chunks = [];
  recorder = new MediaRecorder(new MediaStream(stream.getAudioTracks()), { audioBitsPerSecond: 128000 });
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start(250);

  const t0 = performance.now();
  let floor = 0, frames = 0, speechMs = 0, spoke = false, silenceAt = null, last = t0;
  recorder._send = true;
  recorder.onstop = () => {
    cancelAnimationFrame(vadRaf);
    $("#meTile").classList.remove("speaking");
    if (!recorder._send) return;
    if (!spoke) return listen();
    sendAudio(new Blob(chunks, { type: recorder.mimeType }), recorder.mimeType);
  };

  const tick = (now) => {
    const lvl = level(), dt = now - last; last = now;
    if (now - t0 < 400) { floor += lvl; frames++; vadRaf = requestAnimationFrame(tick); return; }
    const thr = Math.max(0.012, (floor / Math.max(1, frames)) * 2.5);
    const loud = lvl > thr;
    $("#meTile").classList.toggle("speaking", loud);
    if (loud) { speechMs += dt; if (speechMs > 300) spoke = true; silenceAt = null; }
    else if (spoke) {
      silenceAt ??= now;
      if (now - silenceAt > 1800) return stopRecording(true); // 1.8 s of silence ends the answer
    }
    if (now - t0 > 150000) return stopRecording(true);
    vadRaf = requestAnimationFrame(tick);
  };
  vadRaf = requestAnimationFrame(tick);
  recorder._spoke = () => spoke;
}

function stopRecording(send) {
  if (!recorder || recorder.state === "inactive") return;
  recorder._send = send;
  recorder.stop();
  if (send) setPhase("thinking");
}

async function sendAudio(blob, mime) {
  releaseMic();
  setPhase("thinking");
  caption("", "");
  const fd = new FormData();
  fd.append("audio", blob, `answer.${mime.includes("mp4") ? "mp4" : "webm"}`);
  try { handleReply(await postForm(`/i/${token}/audio`, fd)); }
  catch (e) { if (e.status === 409) return otherTab(e.message); caption("", e.message); setTimeout(listen, 1500); }
}

async function sendText(text) {
  if (!text.trim() || st.phase === "thinking") return;
  stopRecording(false);
  releaseMic();
  agentAudio?.pause();
  setPhase("thinking");
  caption("You", text);
  stopVoice();
  try { handleReply({ user_text: text, ...(await api(`/i/${token}/turn`, { method: "POST", body: { text } })) }); }
  catch (e) { if (e.status === 409) return otherTab(e.message); caption("", e.message); setPhase("idle"); }
}

// Another tab or device took over this interview: stop here instead of fighting over the transcript.
function otherTab(msg) {
  stopRecording(false); agentAudio?.pause(); stopMonitor?.();
  stream?.getTracks().forEach((t) => t.stop());
  invalid("This interview is open somewhere else", msg);
}

function handleReply(r) {
  setView(r.interview);
  if (!r.say) { caption("", "Sorry, I didn't catch that. Please go ahead."); return setTimeout(listen, 1200); }
  speakTurn(st.view.turns.at(-1));
}

// ---------- Controls ----------
$("#doneBtn").addEventListener("click", () => {
  if (recorder?._spoke?.()) stopRecording(true);
});

$("#micBtn").addEventListener("click", () => {
  st.micOn = !st.micOn;
  stream?.getAudioTracks().forEach((t) => (t.enabled = st.micOn));
  $("#micBtn").classList.toggle("off", !st.micOn);
  $("#micBtn").textContent = st.micOn ? "Mute" : "Unmute";
  $("#micBtn").setAttribute("aria-pressed", String(!st.micOn));
  if (!st.micOn) { stopRecording(false); setPhase("idle"); }
  else if (st.phase === "idle" && live()) listen();
});

async function setCam(on) {
  if (on && stream && !stream.getVideoTracks().length) {
    try {
      const cam = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
      cam.getVideoTracks().forEach((t) => stream.addTrack(t));
    } catch { on = false; $("#pjStatus").textContent = "Couldn't turn on the camera. You can continue without it."; }
  }
  if (!on) stream?.getVideoTracks().forEach((t) => { t.stop(); stream.removeTrack(t); }); // releases the camera light
  st.camOn = on && !!stream?.getVideoTracks().length;
  for (const v of [$("#preview"), $("#selfVideo")]) { v.srcObject = null; v.srcObject = stream; }
  $("#previewOff").classList.toggle("hidden", st.camOn);
  $("#selfVideo").classList.toggle("hidden", !st.camOn);
  $("#meAvatar").classList.toggle("hidden", st.camOn);
  $("#camBtn").classList.toggle("on", st.camOn);
  $("#pjCam").textContent = st.camOn ? "Turn camera off" : "Turn camera on";
}
$("#camBtn").addEventListener("click", () => setCam(!st.camOn));
$("#pjCam").addEventListener("click", () => setCam(!st.camOn));

$("#ccBtn").addEventListener("click", () => {
  st.cc = !st.cc;
  $("#captions").classList.toggle("off", !st.cc);
  $("#ccBtn").classList.toggle("on", st.cc);
});

function toggleType(force) {
  const open = force ?? $("#typebox").classList.contains("hidden");
  $("#typebox").classList.toggle("hidden", !open);
  $("#typeBtn").classList.toggle("on", open);
  if (open) $("#typeInput").focus();
}
$("#typeBtn").addEventListener("click", () => toggleType());
$("#typeInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) { const t = e.target.value; e.target.value = ""; sendText(t); }
});

$("#endBtn").addEventListener("click", async () => {
  const leave = await confirmDialog({
    title: "Leave the interview?",
    body: "Your answers so far will be shared with the hiring team. You won't be able to rejoin.",
    confirm: "Leave interview", cancel: "Stay", danger: true,
  });
  if (!leave) return;
  stopRecording(false); agentAudio?.pause();
  await api(`/i/${token}/end`, { method: "POST" }).catch(() => {});
  finished();
});

function finished() {
  stopRecording(false);
  stopMonitor?.();
  $("#paused").classList.add("hidden");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  stream?.getTracks().forEach((t) => t.stop());
  show("finished");
  $(st.info?.rated ? "#rated" : "#rateForm").classList.remove("hidden");
}

// The candidate's own rating of the interview, shown to the hiring team. Optional.
$("#rateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const stars = +new FormData(e.target).get("stars");
  if (!stars) return ($("#rateStatus").textContent = "Pick a rating from 1 to 5.");
  $("#rateBtn").disabled = true;
  try {
    await api(`/i/${token}/rating`, { method: "POST", body: { stars, comment: $("#rateComment").value } });
    $("#rateForm").classList.add("hidden"); $("#rated").classList.remove("hidden");
  } catch (err) { $("#rateStatus").textContent = err.message; $("#rateBtn").disabled = false; }
});

init();
