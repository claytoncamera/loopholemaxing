# Creations window — lock status & follow-up

The Creation Engine constellation on `/agora/` (the "view all my creations" window) is
gated. This documents what's live and the remaining work to make it truly private.

## Phase 1 — DONE (soft gate, shipped)
- `/agora/index.html` wraps the Creation Engine sections in `#ce-locked-body`, hidden
  until unlock. A passkey card (`#ce-gate`) is shown instead.
- Passkey is checked client-side with `crypto.subtle` SHA-256 against a digest baked
  into the page. Plaintext is never stored, logged, or persisted.
- Access code is **temporary: `12345`**, to be rotated after first login. There is **no
  in-page "change code" button** in the soft-gate model — to change it, replace
  `EXPECTED_DIGEST` in the gate script with `printf '%s' 'NEWCODE' | shasum -a 256` and
  redeploy (a one-line edit).
- On unlock, `creations.json` is fetched **lazily** and rendered — a locked visitor
  never has the creations data placed in their DOM. Unlock is per browser tab
  (`sessionStorage`).
- The public philosopher reading room on the same page is untouched and stays public.

### Known limit (why Phase 2 exists)
This is a static GitHub Pages site. A client-side gate is a **curtain, not a vault**:
`https://loopholemaxing.com/agora/data/creations.json` is still fetchable directly by
anyone who knows the URL, regardless of the gate. The gate stops casual/other-device
browsing of the window; it does not make the underlying data private.

## Phase 2 — TODO (true server-side lock)
Goal: other devices genuinely cannot read the creations data without authenticating.

1. **Move the data behind the Hub API.** Stop shipping `agora/data/creations.json` as a
   public static file. Serve it from `hubapi.loopholemaxing.com` behind auth, e.g.
   `GET /api/v1/creations` requiring the same session the Army Link/MMS Hub unlock issues
   (`/api/v1/army-link/unlock` is already live — status 405 to OPTIONS confirms it).
2. **Swap the fetch.** In `initCreationGate().reveal()`, replace `loadCreations()`
   (static fetch) with an authenticated `fetch(HUB_ORIGIN + '/api/v1/creations', { credentials, Authorization })`
   using the token returned by the server unlock. Render only on a 2xx.
3. **Reuse the Army Link server-mode pattern.** `army-link/index.html` already implements
   probe -> server unlock -> fail-closed. Port that state machine here so the gate
   validates server-side when reachable and only falls back to the soft check when the
   API is down.
4. **Remove the public JSON from the build.** Delete/relocate `agora/data/creations.json`
   from the Pages artifact so there is no public copy left to fetch.
5. **CORS + cache.** Allow `https://loopholemaxing.com` origin on the Hub endpoint; send
   `Cache-Control: no-store`.

After Phase 2, the soft gate remains as the offline/fallback layer, but the data itself
is unreachable to other devices — the actual "only I can open it" guarantee.
