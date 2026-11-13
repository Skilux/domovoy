import { Conversation } from '@elevenlabs/client';
import { toDynamicVariables } from '../lib/context.js';

const $ = (id) => document.getElementById(id);
const phone = $('phone');
const ringtone = $('ringtone');
const errorLine = $('error');
const transcript = $('transcript');

const TZ = 'Europe/Prague';
const RESULT_SHOWN_MS = 8000;
const END_AFTER_TOOL_MS = 15000;

let call = null;
let pollTimer = null;
let tickTimer = null;

function show(screen) {
  phone.dataset.screen = screen;
}

function showError(text) {
  errorLine.textContent = text || '';
}

function setAddress(text) {
  document.querySelectorAll('[data-address]').forEach((el) => {
    el.textContent = text;
  });
}

function formatWhen(iso) {
  const date = new Date(iso);
  if (!iso || isNaN(date)) return '';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ,
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value || '';
  return `${get('weekday')} ${get('day')} ${get('month')}, ${get('hour')}:${get('minute')}`;
}

async function getJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

async function postResult(result) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch('/api/result', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(result),
      });
      if (res.ok) return true;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  showError('Could not save the call result.');
  return false;
}

function startWaiting() {
  call = null;
  show('waiting');
  clearTimeout(pollTimer);
  poll();
}

async function poll() {
  if (phone.dataset.screen !== 'waiting') return;
  try {
    const { context } = await getJson('/api/pending');
    if (context && typeof context === 'object' && phone.dataset.screen === 'waiting') {
      ring(context);
      return;
    }
  } catch {}
  pollTimer = setTimeout(poll, 1000);
}

function ring(context) {
  call = { context, conversation: null, conversationId: null, result: null, finished: false, hungUp: false, startedAt: 0, endTimer: null };
  showError('');
  setAddress(typeof context.address === 'string' ? context.address : 'Unknown address');
  const rent = document.querySelector('[data-rent]');
  rent.textContent = typeof context.rent === 'number' ? `${context.rent.toLocaleString('en-US').replace(/,/g, ' ')} CZK / month` : '';
  show('incoming');
  ringtone.currentTime = 0;
  ringtone.play().catch(() => showError('Ringtone blocked by the browser.'));
}

function stopRingtone() {
  ringtone.pause();
  ringtone.currentTime = 0;
}

function fallbackResult(current, prefix, summary) {
  return {
    property_id: current.context.property_id,
    conversation_id: current.conversationId || `${prefix}-${Date.now()}`,
    outcome: 'not_booked',
    viewing_start: null,
    answers: [],
    new_costs: [],
    summary,
  };
}

async function finish(current, summary, prefix = 'failed') {
  if (current.finished) return;
  current.finished = true;
  clearInterval(tickTimer);
  clearTimeout(current.endTimer);
  stopRingtone();
  if (!current.result) {
    current.result = fallbackResult(current, prefix, summary);
    await postResult(current.result);
  } else {
    await current.saved;
  }
  showResult(current.result);
}

function showResult(result) {
  const booked = result.outcome === 'booked';
  $('outcome').textContent = booked ? 'Viewing booked' : 'Not booked';
  $('outcome').classList.toggle('booked', booked);
  $('when').textContent = booked ? formatWhen(result.viewing_start) : '';
  $('summary').textContent = typeof result.summary === 'string' ? result.summary : '';
  show('result');
  setTimeout(() => {
    showError('');
    startWaiting();
  }, RESULT_SHOWN_MS);
}

function addLine(role, text) {
  if (!text) return;
  const line = document.createElement('div');
  line.className = `line ${role === 'user' ? 'user' : 'agent'}`;
  const who = document.createElement('b');
  who.textContent = role === 'user' ? 'Realtor' : 'DOMOVOY';
  line.append(who, document.createTextNode(text));
  transcript.append(line);
  transcript.scrollTop = transcript.scrollHeight;
}

function startTimer(current) {
  current.startedAt = Date.now();
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    const s = Math.floor((Date.now() - current.startedAt) / 1000);
    $('timer').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }, 500);
}

function endSession(current) {
  const conversation = current.conversation;
  if (conversation) conversation.endSession().catch(() => {});
}

async function accept() {
  const current = call;
  if (!current || phone.dataset.screen !== 'incoming') return;
  stopRingtone();
  transcript.textContent = '';
  $('timer').textContent = '00:00';
  $('call-status').textContent = 'Connecting';
  $('orb').className = 'orb';
  show('call');

  let signedUrl;
  try {
    signedUrl = (await getJson('/api/signed-url')).signed_url;
    if (!signedUrl) throw new Error('empty signed URL');
  } catch (err) {
    showError(`Could not start the call: ${err.message}`);
    finish(current, 'The call could not start: no signed URL.');
    return;
  }
  if (current.finished) return;

  try {
    current.conversation = await Conversation.startSession({
      signedUrl,
      dynamicVariables: toDynamicVariables(current.context),
      clientTools: {
        submit_call_result: async (parameters) => {
          if (current.result) return 'already saved';
          current.result = {
            outcome: 'not_booked',
            viewing_start: null,
            answers: [],
            new_costs: [],
            summary: '',
            ...(parameters && typeof parameters === 'object' ? parameters : {}),
            property_id: current.context.property_id,
            conversation_id: current.conversationId || current.conversation?.getId() || `failed-${Date.now()}`,
          };
          current.saved = postResult(current.result);
          current.endTimer = setTimeout(() => endSession(current), END_AFTER_TOOL_MS);
          return (await current.saved) ? 'saved' : 'save failed';
        },
      },
      onConnect: ({ conversationId }) => {
        current.conversationId = conversationId;
        $('call-status').textContent = 'In call';
        startTimer(current);
      },
      onDisconnect: (details) => {
        if (details?.reason === 'error') showError(`Call dropped: ${details.message}`);
        finish(current, current.hungUp ? 'The call was hung up before a result was saved.' : 'The call ended before a result was saved.');
      },
      onError: (message) => {
        showError(`Call error: ${message}`);
      },
      onMessage: ({ message, role, source }) => {
        addLine(role || (source === 'user' ? 'user' : 'agent'), message);
      },
      onModeChange: ({ mode }) => {
        $('orb').className = `orb ${mode}`;
      },
    });
    if (!current.conversationId) current.conversationId = current.conversation.getId();
    if (current.finished) endSession(current);
  } catch (err) {
    showError(`Could not start the call: ${err?.message || err}`);
    finish(current, 'The call could not start.');
  }
}

function decline() {
  const current = call;
  if (!current || phone.dataset.screen !== 'incoming') return;
  finish(current, 'The call was declined.', 'declined');
}

function hangUp() {
  const current = call;
  if (!current || current.finished) return;
  current.hungUp = true;
  if (current.conversation) {
    endSession(current);
    setTimeout(() => finish(current, 'The call was hung up before a result was saved.'), 2000);
  } else {
    finish(current, 'The call was hung up before a result was saved.');
  }
}

async function ready() {
  const button = $('ready');
  button.disabled = true;
  showError('');
  const unlock = ringtone.play().then(() => {
    ringtone.pause();
    ringtone.currentTime = 0;
  });
  try {
    await unlock;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
  } catch (err) {
    button.disabled = false;
    showError(`Microphone or sound is blocked: ${err?.message || err}`);
    return;
  }
  startWaiting();
}

$('ready').addEventListener('click', ready);
$('accept').addEventListener('click', accept);
$('decline').addEventListener('click', decline);
$('hangup').addEventListener('click', hangUp);
