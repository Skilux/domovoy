# DOMOVOY phone

Vercel app at https://domovoy-phone.vercel.app. Spec: [docs/prd/voice.md](../docs/prd/voice.md).

- `api/`: the 5 routes from the spec. `lib/store.js` is the only file that knows the store (Upstash Redis REST, 1 hour expiry).
- `lib/context.js`: the only place with `call_context` field names. Required: `property_id`, `address`. Every other field passes through to the agent as a dynamic variable and as a line in `context_text`.
- `src/main.js` + `public/`: the page. `npm run build` bundles it into `public/app.js`.
- `agent/`: ElevenLabs agent prompt and config. Recreate or update with `set -a; . ~/.config/domovoy/.env; set +a; node phone/agent/sync-agent.mjs`. After every sync, also run `python3 posthog/calls.py prompt` from the repo root: it records the deployed prompt as a version of `domovoy-voice-agent` in PostHog, so call traces carry the prompt version. If that command fails, the prompt deploy still counts.

Env in Vercel: `DOMOVOY_SECRET`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `KV_REST_API_URL`, `KV_REST_API_TOKEN`.

Ring the page (open it and click Ready first):

```sh
curl -X POST https://domovoy-phone.vercel.app/api/call \
  -H "x-domovoy-secret: $DOMOVOY_SECRET" -H 'content-type: application/json' \
  -d @phone/example-context.json
curl https://domovoy-phone.vercel.app/api/result/demo-vinohrady-001 -H "x-domovoy-secret: $DOMOVOY_SECRET"
```

`example-context.json` and `public/ringtone.mp3` (cut from the Nokia 3310 video named in the docs) are demo fixtures; the context is synthetic.
