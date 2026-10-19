// Candidate interview, video-call style: pre-join (camera, mic, resume, consent) -> call -> finished.
// Turn-taking: interviewer speaks (Piper audio) -> we listen with voice-activity detection -> the answer is
// transcribed by Whisper on the server -> next question. Typing is always available.
import { $, api, confirmDialog, esc, fmt, postForm } from "/static/common.js";

const token = location.pathname.split("/").pop();
const st = { info: null, view: null, syncedAt: 0, phase: "idle", micOn: true, camOn: false, cc: true, resumeOk: false };
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

const show = (id) => ["prejoin", "call", "finished", "invalid"].forEach((v) => $(`#${v}`).classList.toggle("hidden", v !== id));
const live = () => ["INTERVIEWING", "WRAPUP"].includes(st.view?.state);

// ---------- Pre-join ----------
async function init() {
  try { st.info = await api(`/i/${token}`); }
  catch (e) { $("#invalidMsg").textContent = e.message; return show("invalid"); }
  const info = st.info;
  if (info.interview) {
    st.view = info.interview;
    if (!live()) return finished(info.feedback);
  }
  st.resumeOk = info.has_resume || !!info.interview;
  $("#pjTitle").textContent = info.interview ? "Rejoin your interview" : `Hi ${info.name.split(" ")[0]}, ready to join?`;
  $("#pjSub").textContent = `${info.role_title}${info.company ? ` · ${info.company}` : ""} · about ${info.minutes} minutes with an AI interviewer`;
  $("#resumeBox").classList.toggle("hidden", st.resumeOk);
  show("prejoin");
  await openDevices();
  updateJoin();
}

async function openDevices() {
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  // Camera is off by default and only requested when the candidate turns it on.
  try { stream = await navigator.mediaDevices.getUserMedia({ audio }); }
  catch { $("#pjStatus").textContent = "No microphone access. You can still join and type your answers."; return; }
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

function updateJoin() { $("#joinBtn").disabled = !($("#consent").checked && st.resumeOk); }
$("#consent").addEventListener("change", updateJoin);

$("#resumeBtn").addEventListener("click", async (e) => {
  const fd = new FormData();
  if ($("#resumeFile").files[0]) fd.append("file", $("#resumeFile").files[0]);
  else fd.append("text", $("#resumeText").value);
  e.target.disabled = true;
  const stop = resumeLoader(true);
  try {
    await postForm(`/i/${token}/resume`, fd);
    stop();
    st.resumeOk = true;
    $("#resumeBox").classList.add("done");
    $("#resumeStatus").textContent = "Resume read. Your interview is ready.";
    updateJoin();
  } catch (err) { stop(); $("#resumeStatus").textContent = err.message; e.target.disabled = false; $("#resumeFile").value = ""; }
});
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

$("#resumeFile").addEventListener("change", () => {
  const f = $("#resumeFile").files[0];
  if (f) { $("#resumeLabel").textContent = f.name; $("#resumeBtn").click(); }
});

$("#joinBtn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#pjStatus").textContent = "Connecting...";
  try {
    await audioCtx?.resume();
    releaseMic(); // let the phone settle on the loudspeaker while the interview loads
    if (!st.view) st.view = await api(`/i/${token}/start`, { method: "POST" });
    enterCall();
  } catch (err) { $("#pjStatus").textContent = err.message; e.target.disabled = false; }
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

function setView(v) { st.view = v; st.syncedAt = Date.now(); }

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
      b.style.height = `${12 + Math.max(0, v) * 96}px`;
    });
    voiceRaf = requestAnimationFrame(step);
  };
  voiceRaf = requestAnimationFrame(step);
}
function stopVoice() { cancelAnimationFrame(voiceRaf); bars().forEach((b) => (b.style.height = "12px")); }

function speakTurn(turn) {
  stopRecording(false);
  releaseMic(); // normally already released when the answer was sent
  setPhase("speaking");
  caption("Interviewer", turn.text);
  const after = () => { stopVoice(); agentAudio = null; if (live()) listen(); else finished(); };
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
  // Fallback when Piper is unavailable.
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
  if (!live()) return;
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
  catch (e) { caption("", e.message); setTimeout(listen, 1500); }
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
  catch (e) { caption("", e.message); setPhase("idle"); }
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

async function finished(feedback) {
  stopRecording(false);
  stream?.getTracks().forEach((t) => t.stop());
  show("finished");
  if (feedback === undefined) { try { feedback = (await api(`/i/${token}`)).feedback; } catch {} }
  if (feedback) { $("#feedback").classList.remove("hidden"); $("#feedbackText").textContent = feedback; }
}

init();
