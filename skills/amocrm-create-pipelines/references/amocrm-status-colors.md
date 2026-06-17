# amoCRM Status Colors

Source: https://www.amocrm.ru/developers/content/crm_platform/leads_pipelines

amoCRM accepts only this whitelist for custom status `color` values:

```text
#fffeb2
#fffd7f
#fff000
#ffeab2
#ffdc7f
#ffce5a
#ffdbdb
#ffc8c8
#ff8f92
#d6eaff
#c1e0ff
#98cbff
#ebffb1
#deff81
#87f2c0
#f9deff
#f3beff
#ccc8f9
#eb93ff
#f2f3f4
#e6e8ea
```

Use these defaults for new pipelines:

| Meaning | Color |
|---|---|
| First/new fact | `#fffeb2` |
| Qualified/discovered | `#ffdc7f` |
| Problem/risk/attention | `#ff8f92` |
| Proposal sent/approval | `#c1e0ff` |
| Agreement/start | `#deff81` |
| Handoff/production | `#87f2c0` |
| Nurture/retention | `#f3beff` |
| Neutral/admin | `#e6e8ea` |

Validation rules:

- Always set `color` on each custom status created by this skill.
- Never invent colors outside the whitelist.
- Keep colors lowercase in request payloads.
- System statuses 142 and 143 are managed by amoCRM; do not try to recolor them in normal setup flows.
