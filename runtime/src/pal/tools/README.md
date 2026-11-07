# Tools

Bots get in-process tools from **tool providers**. Each provider subclasses
`ToolProvider`, builds its tools per bot from a `ToolContext`, and is added to
the `ToolRegistry`. A provider's tools appear to the bot as
`mcp__pal_<provider>__<tool>`.

Set `requires_display = True` on a provider whose tools drive the desktop: the
runtime then wakes the bot's display before any of those tools run and counts
their use as display activity, which keeps the display from going to sleep.

```
tools/
  base.py        ToolProvider, ToolContext, result helpers
  registry.py    ToolRegistry
  builtin/       providers that ship with the runtime
    memory.py    remember, recall, read_memory, forget
    team.py      list_bots, message_bot
    display.py   use_display, display_status
```

Custom computer-control tools and integrations (such as the custom Gmail tool)
are added as new providers next to `builtin/`.
