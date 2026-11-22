<img src="docs/logo.png" alt="HAI" height="64">

# HAI - Your home AI Agent: Home Assistant integration

Talk to **HAI**, your home AI agent, through Home Assistant: typed in Assist, or by voice on a voice satellite.

This integration connects Home Assistant to HAI (the Home Assistant add-on
[`jcustovic/hai-home-assistant-addon`](https://github.com/jcustovic/hai-home-assistant-addon), or
the same container in Docker) and makes it a **conversation agent** in Assist. Everything you say goes to the
container, which answers and acts on your home itself. The integration only carries your words there and the
reply back.

- **Home Assistant sends no tools and no prompt.** The integration sends your text (and the Assist language,
  as a hint) to the container's chat API and reads out its reply. What the assistant may do, which actions it
  asks you to confirm first, and what it knows about your home are all decided in the container.
- **Confirmations work through Assist.** When the container holds a sensitive action ("Unlock the front
  door?"), your "yes" goes to the same conversation and releases it.
- **Plain spoken errors.** If the container is off, still being set up, or no longer accepts the password,
  Assist says so in a sentence instead of failing silently.

<!-- ha-marketplace:exclude-start -->
## Install

[![Open this repository in the Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=jcustovic&repository=hai-home-assistant-integration&category=integration) [![Set up HAI](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hai_agent)

1. Install it: the first button opens this repository in your Home Assistant's Marketplace (HACS before Home
   Assistant 2026.11) and offers to add it. Or copy `custom_components/hai_agent/` into your configuration's
   `custom_components/`. Restart Home Assistant.
2. Add it: the second button, or **Settings → Devices & services → Add integration → HAI - Your home AI Agent**.
<!-- ha-marketplace:exclude-end -->

## Set up

**With the HAI add-on** (Home Assistant OS): nothing to type. When the add-on is set up and running,
**Settings → Devices & services** shows **Discovered: HAI - Your home AI Agent**. Press **Add** and confirm; the add-on supplies its
address and chat password, and after a password reset the integration takes the new one by itself.

**Otherwise** (a Docker container, or adding it by hand) you need the container's address and its **chat password**
(shown once when the container was set up):

1. Enter the container's address, for example `http://192.168.1.20:8099`, or `http://<your Home Assistant>:8099`
   when it runs as the add-on, and the chat password. Both are checked before anything is saved.
2. **Settings → Voice assistants:** choose **HAI - Your home AI Agent** as the conversation agent of a voice assistant. Leave
   Home Assistant's own "Control Home Assistant" off: the container does the controlling.
3. Consider turning off **Prefer handling commands locally** in that voice assistant: with it on, Home Assistant
   answers simple commands itself, without the container and without its confirmations.

**Lost or changed the password?** With the add-on there is nothing to do here. Otherwise reset it in the container (inside Home Assistant: the add-on's page → Account →
*Reset chat password*; in Docker: `docker exec <container> hai-agent reset-password`). Home Assistant then says the
saved password was not accepted and asks for the new one under Settings → Devices & services.

| What you see | What it means |
|---|---|
| "Nothing answered at that address" | The container is off, or the address or port is wrong. |
| "has not finished its setup yet" | The container is still on its first-run page: finish it there, then enter the password it shows. |
| "older HAI container" | Update the container. |
| "does not look like an HAI container" | Something else answers at that address. |
| Assist: "can't reach HAI" | The container is off; the integration keeps trying. |

Requires Home Assistant **2026.10.1** or newer.

## Status

Tried by hand in Home Assistant 2026.10.1: setup, commands in Assist, and a held action released by "yes" (typed).
**Not tried yet:** a voice satellite.

## Develop

```bash
uv sync && uv run ruff check . && uv run pytest     # Python 3.14 (required by Home Assistant 2026.10)
```

The tests run Home Assistant itself against a mocked container (no model call, no browser).

```
hacs.json                         name and minimum Home Assistant version
custom_components/hai_agent/      the integration: api.py (the container client), config_flow.py, conversation.py,
                                  brand/ (icon and logo, shown by Home Assistant 2026.3+)
contract/chat-api/                a copy of the chat API the container publishes; this client is tested against it
tests/                            config flow, set-up, conversation, contract and brand-image tests
```

`contract/chat-api/` is not edited here: it is copied from `hai-agent`, which owns the API, whenever that changes.
