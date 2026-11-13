# DOMOVOY phone

Vercel app at https://domovoy-phone.vercel.app. Spec: [docs/prd/voice.md](../docs/prd/voice.md).

## Which URL when

| URL | Shows | Use it for |
| --- | --- | --- |
| `/` | Home: pitch, install prompt, QR, and the live phone on the right. The phone unfolds over the pitch on Accept. The address bar shows `/start`; both addresses are the same page. | The submission form, judges, a new user, and the stage screen |
| `/phone` | The phone alone | A screen that should show only the phone |
| `/stage` | The stage rail, 8 states | The stage, next to Claude Code |
| `/prompt.txt` | The install prompt as plain text | `claude "$(curl -fsSL https://domovoy-phone.vercel.app/prompt.txt)"` |

Pairing is per browser. Open `/?k=<DOMOVOY_RECEIVER_KEY>` once (`/start?k=` and `/phone?k=` do the same); after that every phone page in that browser is paired, and the key is gone from the address bar. A visitor without the key sees the home page with a phone that says "Demo phone. Calls ring only on the paired device."; it never rings for them.

- Rehearsal: one tab, `/`, in the paired browser. Click Ready on the phone. Close the tab when done.
- Stage, Vladimir's laptop: tab 1 `/` (paired, Ready clicked), tab 2 `/stage`, plus Claude Code and Notion.
- Keep exactly one phone page open in a paired browser. Two open pages are two phones, and only one of them gets the call.
- Submission form: `https://domovoy-phone.vercel.app`.

## Layout

- `api/`: the 5 routes from the spec. `lib/store.js` is the only file that knows the store (Upstash Redis REST, pending calls expire after 1 hour, results after 24 hours).
- `lib/context.js`: the only place with `call_context` field names. Required: `property_id`, `address`. Every other field passes through to the agent as a dynamic variable and as a line in `context_text`.
- `src/main.js` + `public/phone.html`: the phone page, served at `/phone`. `public/start.html` is the home page; `vercel.json` redirects `/` to it and keeps the query, so `/?k=` still pairs. `npm run build` bundles it into `public/app.js`.
- `public/prompt.txt`: the install prompt, the only copy to edit. `/start` shows it and the terminal one-liner on that page fetches it. `public/qr.svg` is a static QR for `https://domovoy-phone.vercel.app/start`, made once with `npx qrcode@1.5.4 -t svg`; it never carries the `?k=` key.
- `agent/`: ElevenLabs agent prompt and config. Recreate or update with `set -a; . ~/.config/domovoy/.env; set +a; node phone/agent/sync-agent.mjs`. After every sync, also run `python3 posthog/calls.py prompt` from the repo root: it records the deployed prompt as a version of `domovoy-voice-agent` in PostHog, so call traces carry the prompt version. If that command fails, the prompt deploy still counts.
- `public/stage.html`: the stage rail for the demo, at `/stage`. A narrow window shows only the rail (FIND, APPROVE, CALL, BOOK, LEARN); a wide window shows the title, the close and labeled placeholders with sample data. Right arrow, Space or click = next, Left arrow = back, digits jump. `?rail=1` or `?full=1` forces a mode. Edit the `STATUS` object at the top of its script to change a status chip. It calls no API.

Env in Vercel: `DOMOVOY_SECRET`, `DOMOVOY_RECEIVER_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `KV_REST_API_URL`, `KV_REST_API_TOKEN`.

## Deploying

Production is a manual `vercel deploy --prod` from `phone/`, not a GitHub deploy. The Vercel link (`phone/.vercel`) exists only in the Voice lead's worktree. Several threads change this site, so a deploy from a feature branch or a stale checkout removes other people's pages from production.

Deploy only from a checkout that is exactly fresh `origin/main`:

```sh
git fetch origin && git checkout --detach origin/main
git status --short            # must print nothing
git rev-parse HEAD origin/main  # both lines must be equal
cd phone && npm run build && vercel deploy --prod --yes
```

After every deploy, check (expect 307, 200, 200, 200, 200, then 401):

```sh
for p in / /phone /start /stage /prompt.txt /api/pending; do
  curl -s -o /dev/null -w "$p %{http_code}\n" https://domovoy-phone.vercel.app$p
done
```

## Testing on production

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
- Results stay readable for 24 hours unless a new call for the same `property_id` clears them. A pending call nobody answers expires after 1 hour.

`test-context.json` is the synthetic context for these tests. `example-context.json` and `public/ringtone.mp3` (cut from the Nokia 3310 video named in the docs) are demo fixtures; the context is synthetic.
