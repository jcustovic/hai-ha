# Chat API — published contract

What HAI container (`hai-agent`) promises to callers that talk to the agent from outside its own
web page, such as the Home Assistant integration `hai-home-assistant-integration`. `hai-agent` **owns** these files and its tests check
the container against them. A client keeps a copy and tests itself against it; the copy is refreshed from
`hai-agent` whenever the API changes, never edited on its own.

Changes are additive (new optional fields): an old client must keep working.

## `POST /api/chat`

| | |
|---|---|
| Auth | the chat password: `Authorization: Bearer <password>` (or `X-Chat-Token`). Repeated wrong values lock the caller out for a while |
| Body | [`chat_request.schema.json`](chat_request.schema.json): `session_id`, `text`, optional `language`, optional `source` (`web` default, `ha`), optional `stream` (default `false`) |
| `200` | without `stream`: [`chat_response.schema.json`](chat_response.schema.json): `text` is always what to show or speak. A provider failure is still a 200 (`error_kind` and `error_detail` say what happened), and so is a Home Assistant that cannot be reached (`error_kind: ha_unreachable`; `text` says where to fix the ha-mcp address) |
| `401` | missing or wrong password |
| `422` | the body does not match the request schema (for example an invalid `language`) |
| `429` | too many failed passwords, or too many chat requests; honour `Retry-After` |

### Streaming the reply (`"stream": true`)

With `"stream": true` the same endpoint answers `200` with `Content-Type: text/event-stream` and sends the
reply while it is written. Each event is one line `data: <JSON>` and a blank line, described by
[`chat_stream_event.schema.json`](chat_stream_event.schema.json):

- `{"type": "delta", "text": "…"}`: the next piece of the answer; append it.
- `{"type": "step", "text": "…"}`: what the agent is doing now ("Step 2: waiting for the model…", or the tool it
  runs, such as "Step 1: get_state(entity_id=light.kitchen)"), for a progress line while no text has come yet.
  It is not part of the answer and carries no private text; ignore it if you have no use for it.
- `{"type": "reset"}`: what was shown so far was not the answer (the model wrote a sentence and then went on to
  look something up or act); clear it.
- `{"type": "done", "session_id", "text", "error_kind", "error_detail"}`: exactly once, last: the same reply as the
  JSON body, including provider failures. **`text` is the answer and replaces what was streamed**, so a caller
  can ignore `step`, `delta` and `reset` altogether and use only `done`.

Auth, rate limits and a bad body are refused before the stream starts, with the usual status codes and no
stream. After it has started the status is already `200`: a failure arrives as a `done` event with `error_kind`.
A stream that ends without `done` was cut off. Closing the connection does not stop the command: it finishes,
is logged, and its answer is kept in the history. Callers that do not send `stream` get the JSON body as before.
Some text is provisional: a held action ("Unlock the front door?") can follow text such as "Door unlocked" that the model
wrote before the safety check, so show only `done.text` where a wrong sentence would matter (voice, notifications).

## `GET /api/auth/check`

Same auth as above. `200` with `{"status": "ok"}` when the password is right (no model call, nothing spent),
`401` when it is wrong, `429` when locked out. Lets a caller validate a password when it is entered, and
notice later that it was changed, without sending a chat message.

## `GET /healthz`

No auth, reveals nothing else. `200` with `{"status": "ok"}` when the agent is running, or
`{"status": "setup"}` while the container waits for its first-run setup (or a re-enrollment). In setup the
two endpoints above do not exist yet (`404`), so a caller that gets a `404` reads this to tell "finish the
container's setup first" (`setup`) from "an older container without `/api/auth/check`" (`ok`) and from
"not an HAI at all" (anything else).

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
- **The agent forgets an idle conversation** (an hour without a message by default, or sooner if the
  container is busy with many conversations). A message sent after that is answered without the earlier turns,
  and the reply says so with `remembered: false` (also `false` for a first message), so a caller can tell the
  user that earlier messages are no longer remembered. A question waiting for a "yes" lasts five minutes.
- **A command can take a while** (several model calls, tools run locally): use a generous timeout, at least 60 s.
- **The password can be replaced** (Account → *Reset chat password* inside Home Assistant, or
  `hai-agent reset-password` on the machine); the old one stops working at once. A caller then gets `401` and
  should ask the user for the new one.
- `language` only helps when the agent is unsure; it never overrides the language the user wrote in.
