# DOMOVOY phone

Vercel app at https://domovoy-phone.vercel.app. Spec: [docs/prd/voice.md](../docs/prd/voice.md).

- `api/`: the 5 routes from the spec. `lib/store.js` is the only file that knows the store (Upstash Redis REST, 1 hour expiry).
- `lib/context.js`: the only place with `call_context` field names. Required: `property_id`, `address`. Every other field passes through to the agent as a dynamic variable and as a line in `context_text`.
- `src/main.js` + `public/`: the page. `npm run build` bundles it into `public/app.js`.
- `public/prompt.txt`: the install prompt, the only copy to edit. `/start` shows it and the terminal one-liner on that page fetches it. `public/qr.svg` is a static QR for `https://domovoy-phone.vercel.app/start`, made once with `npx qrcode@1.5.4 -t svg`; it never carries the `?k=` key.
- `agent/`: ElevenLabs agent prompt and config. Recreate or update with `set -a; . ~/.config/domovoy/.env; set +a; node phone/agent/sync-agent.mjs`. After every sync, also run `python3 posthog/calls.py prompt` from the repo root: it records the deployed prompt as a version of `domovoy-voice-agent` in PostHog, so call traces carry the prompt version. If that command fails, the prompt deploy still counts.

Env in Vercel: `DOMOVOY_SECRET`, `DOMOVOY_RECEIVER_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `KV_REST_API_URL`, `KV_REST_API_TOKEN`.

Test on production (open the paired URL `$PHONE_URL/?k=$DOMOVOY_RECEIVER_KEY` and click Ready first):

```sh
set -a; . ~/.config/domovoy/.env; set +a
ID=test-voice-$(date +%H%M%S)
sed "s/test-voice-001/$ID/" phone/test-context.json | curl -X POST $PHONE_URL/api/call \
  -H "x-domovoy-secret: $DOMOVOY_SECRET" -H 'content-type: application/json' -d @-
curl $PHONE_URL/api/result/$ID -H "x-domovoy-secret: $DOMOVOY_SECRET"
```

Rules for tests on production:
- Every test uses its own `property_id` that starts with `test-`. Never `demo-vinohrady-001` and never the id of a real flat: a new `POST /api/call` deletes the stored result for its `property_id`.
- Clear only results you created.
- Any paired page takes the next call. Keep one paired page open, and none while someone rehearses.
- Every key in the store expires after 1 hour, results included. Save a result you want to keep.

`test-context.json` is the synthetic context for these tests. `example-context.json` and `public/ringtone.mp3` (cut from the Nokia 3310 video named in the docs) are demo fixtures; the context is synthetic.
