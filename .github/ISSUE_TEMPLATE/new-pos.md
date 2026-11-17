---
name: New pos request
about: Ask for (or offer) support for another agent or app
title: "pos: <platform>"
labels: pos
---

**Platform / agent**: name, version, link.

**How do you run it?** (terminal, IDE, desktop app, inside another tool)

**How could SeKantor see its state?** Anything you know: hooks, a local API, log files, a CLI,
its process name, env vars. A `scripts/probe_hosts.py -o probe.json` run while it waits for you
helps a lot (check the file for secrets first).

**How could SeKantor tell when it is waiting, working or done?** (a hook event, a prompt on screen, an API field, a process state)

**Will you write it?** See docs/writing-a-pos.md.
