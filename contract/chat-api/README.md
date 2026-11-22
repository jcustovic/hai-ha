# Chat API — published contract

What the HA AI Agent container (`hai-agent`) promises to callers that talk to the agent from outside its own
web page, such as the Home Assistant integration `hai-ha`. `hai-agent` **owns** these files and its tests check
the container against them. A client keeps a copy and tests itself against it; the copy is refreshed from
`hai-agent` whenever the API changes, never edited on its own.

Changes are additive (new optional fields): an old client must keep working.

## `POST /api/chat`

| | |
|---|---|
| Auth | the chat password: `Authorization: Bearer <password>` (or `X-Chat-Token`). Repeated wrong values lock the caller out for a while |
| Body | [`chat_request.schema.json`](chat_request.schema.json): `session_id`, `text`, optional `language`, optional `source` (`web` default, `ha`) |
| `200` | [`chat_response.schema.json`](chat_response.schema.json): `text` is always what to show or speak. A provider failure is still a 200 (`error_kind` and `error_detail` say what happened) |
| `401` | missing or wrong password |
| `422` | the body does not match the request schema (for example an invalid `language`) |
| `429` | too many failed passwords, or too many chat requests; honour `Retry-After` |

## `GET /api/auth/check`

Same auth as above. `200` with `{"status": "ok"}` when the password is right (no model call, nothing spent),
`401` when it is wrong, `429` when locked out. Lets a caller validate a password when it is entered, and
notice later that it was changed, without sending a chat message.

## `GET /healthz`

No auth, reveals nothing else. `200` with `{"status": "ok"}` when the agent is running, or
`{"status": "setup"}` while the container waits for its first-run setup (or a re-enrollment). In setup the
two endpoints above do not exist yet (`404`), so a caller that gets a `404` reads this to tell "finish the
container's setup first" (`setup`) from "an older container without `/api/auth/check`" (`ok`) and from
"not an HA AI Agent at all" (anything else).

## Home Assistant discovery (add-on only)

Running as a Home Assistant add-on, the container announces itself through the Supervisor (`POST /discovery`)
for the integration domain `hai_agent`, at start and again whenever its chat password changes:

```json
{"service": "hai_agent", "config": {"host": "abcd1234-hai-agent", "port": 8099, "password": "…"}}
```

`host` is the add-on's name on Home Assistant's internal network and `port` the container's port, so the
caller's address is `http://<host>:<port>`; `password` is the chat password for the endpoints above. Home
Assistant gives it to the integration's `hassio` config-flow step (`HassioServiceInfo.config`, with the add-on's
`slug` and `name`). Only Home Assistant Core can read discovery messages; other add-ons cannot. Outside an add-on
nothing is announced.

Notes for callers:

- **Send only the new message.** The agent keeps the conversation under `session_id` (bounded and expiring).
  A caller that has its own conversation id uses it as `session_id`.
- **A confirmation is an ordinary reply.** A sensitive action is held and the reply is a question ("Unlock the
  front door?"). The user's next message **in the same session** is the answer; anything but a clear yes
  cancels it, and so does waiting more than five minutes.
- **A command can take a while** (several model calls, tools run locally): use a generous timeout, at least 60 s.
- **The password can be replaced** (Account → *Reset chat password* inside Home Assistant, or
  `hai-agent reset-password` on the machine); the old one stops working at once. A caller then gets `401` and
  should ask the user for the new one.
- `language` only helps when the agent is unsure; it never overrides the language the user wrote in.
