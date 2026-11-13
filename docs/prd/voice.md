# Lane: Voice

Owner: Danila. Priority: P0. Code: `phone/`.

A phone page that waits, rings when Claude sends a flat, runs a live English conversation through an ElevenLabs agent, and hands the result back to Claude.

## Definition of done

- [ ] The phone app is deployed on Vercel at a public URL.
- [ ] `POST /api/call` with a valid `call_context` makes the open page show an incoming call with the flat's address and play the Nokia 3310 ringtone, with no click on the page.
- [ ] Accept starts a live ElevenLabs session. The agent knows the flat, the unknowns to ask about and the free windows.
- [ ] The agent asks about the unknowns, agrees a viewing time inside a free window, then calls `submit_call_result` and ends the call.
- [ ] `GET /api/result/{property_id}` returns that result to Claude.
- [ ] The ElevenLabs API key exists only on the server. The agent's allowlist has the Vercel domain.
- [ ] A hand-written context works end to end by 14:00, before the Actor lane is ready.
- [ ] Rehearsed on Vladimir's laptop with the venue's audio and Wi-Fi.

## Diagram

```mermaid
stateDiagram-v2
  [*] --> Waiting
  Waiting --> Ringing: pending call_context arrives
  Ringing --> InCall: Accept
  Ringing --> Waiting: Decline (result = not_booked)
  InCall --> Result: agent calls submit_call_result
  InCall --> Result: call drops (result = not_booked)
  Result --> Waiting: after receipt shown
```

```mermaid
sequenceDiagram
  participant C as Claude Code
  participant S as Server (Vercel)
  participant P as Phone page
  participant E as ElevenLabs
  C->>S: POST /api/call (call_context, secret header)
  P->>S: GET /api/pending (poll every 1 s)
  S-->>P: call_context
  Note over P: Ring, wait for Accept
  P->>S: GET /api/signed-url
  S->>E: Request signed URL (API key)
  S-->>P: signed URL
  P->>E: startSession(signedUrl, dynamicVariables)
  E->>P: client tool submit_call_result
  P->>S: POST /api/result
  C->>S: GET /api/result/{property_id}
  S-->>C: result, or 404 while pending
```

## Details

### API

| Route | Caller | Does |
| --- | --- | --- |
| `POST /api/call` | Claude | Validates and stores the `call_context` as the pending call. Requires header `x-domovoy-secret`. |
| `GET /api/pending` | Page | Returns the pending context once, then clears it. |
| `GET /api/signed-url` | Page | Returns a short-lived ElevenLabs signed URL. |
| `POST /api/result` | Page | Stores the result by `property_id`. A repeated `conversation_id` is ignored. |
| `GET /api/result/{property_id}` | Claude | Returns the result, or 404 while the call is running. Requires the secret header. |

Contracts for `call_context` and `submit_call_result` are in [plan.md](../plan.md#contracts).

Vercel functions share no memory, so pending calls and results need a small store. Recommended: Upstash Redis from the Vercel Marketplace, with a 1-hour expiry on every key.

### Page

- Screens: waiting → incoming call (address, Accept / Decline, ringtone) → in call (timer, live transcript) → result (outcome and time).
- Browsers block audio until the user interacts with a page. The waiting screen needs one "Ready" click before the demo so the ringtone can play later.
- Ringtone: an mp3 cut from the referenced Nokia 3310 video.

### ElevenLabs agent

- English. One client tool, `submit_call_result`, plus the built-in end-call. No other tools.
- Dynamic variables: the `call_context` fields. `available_windows` and `unknowns` are passed as readable text.
- Prompt rules: say it is an AI assistant calling for the renter; ask each unknown once; propose times only from the free windows; confirm the agreed time back before saving; call `submit_call_result` exactly once; never agree to payments or anything beyond a viewing.
- `outcome` is `booked` only after the realtor explicitly agrees to a time inside a window. Anything else is `not_booked`.

## Decisions

- Browser WebRTC, no Twilio, no real phone number. Said plainly on stage.
- English only. One call per demo. Happy path only; no negotiation.
- Vercel for both the demo and the submission link.
- Result relay: ElevenLabs client tool → page → server → Claude polls.
- Danila plays the demo realtor on Vladimir's laptop.

## Open items

From [open-items.md](../open-items.md): 9 (voice, persona, first message, `agent_id`, allowlist). New for this lane: confirm the store choice above; pick the value of `x-domovoy-secret` and share it with the Skill lane.
