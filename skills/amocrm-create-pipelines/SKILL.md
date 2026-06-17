---
name: amocrm-create-pipelines
description: Create or redesign amoCRM lead pipelines and statuses using the communication-fact method. Use when the user asks to create a sales funnel, воронку, pipeline, stages/statuses, этапы продаж, or to configure amoCRM pipelines with fact-based past-tense communication stages and explicit amoCRM status colors.
---

# amoCRM Pipeline Creation

Use this skill to design and create amoCRM lead pipelines through the amoCRM MCP server.

## Required Context

Read these references before creating or changing a pipeline:

- `references/communication-fact.md` for the communication-fact method.
- `references/amocrm-status-colors.md` for the allowed amoCRM status color whitelist.

## Workflow

1. Check access with `amocrm_get_account`.
2. Ask for the business model only if it is unknown. Otherwise infer a practical pipeline from the user's niche.
3. Draft statuses as completed facts in past tense.
4. Map every external or internal customer-moving action to a separate status.
5. Assign a valid amoCRM color to every custom status. Never invent hex colors.
6. Create the pipeline with `amocrm_pipelines` or `amocrm_resource_action`.
7. Read the pipeline back and verify that all custom statuses have the intended names and colors.
8. Report pipeline ID, status IDs, and any statuses that amoCRM changed or rejected.

## Communication-Fact Rules

Status names must describe facts that already happened, not intentions or tasks.

Use:

- `Получен новый лид`
- `Проведена квалификация`
- `Отправлено КП`
- `Согласован старт`
- `Сформирован договор`
- `Передан в производство`

Avoid:

- `Позвонить клиенту`
- `Ждем ответ`
- `В работе`
- `КП`
- `Договор`

If a user proposes vague statuses, rewrite them as facts before creating the pipeline.

## Status Color Rules

Every status created through this skill must include `color`.

Use a left-to-right progression:

- Early/new: `#fffeb2`, `#fffd7f`, `#fff000`
- Qualification/discovery: `#ffeab2`, `#ffdc7f`, `#ffce5a`
- Risk/blocked/needs attention: `#ffdbdb`, `#ffc8c8`, `#ff8f92`
- Proposal/approval: `#d6eaff`, `#c1e0ff`, `#98cbff`
- Agreement/launch: `#ebffb1`, `#deff81`, `#87f2c0`
- Service/retention or soft stages: `#f9deff`, `#f3beff`, `#ccc8f9`, `#eb93ff`
- Neutral/admin: `#f2f3f4`, `#e6e8ea`

Do not set colors for system statuses 142 and 143 unless amoCRM documentation explicitly allows the target operation.

## Creation Payload Pattern

Use this shape when creating a pipeline:

```json
[
  {
    "name": "B2B продажи | Коммуникация-факт",
    "is_main": false,
    "is_unsorted_on": true,
    "sort": 100,
    "_embedded": {
      "statuses": [
        {
          "name": "Получен новый лид",
          "sort": 10,
          "color": "#fffeb2"
        },
        {
          "name": "Проведена квалификация",
          "sort": 20,
          "color": "#ffdc7f"
        },
        {
          "name": "Отправлено КП",
          "sort": 30,
          "color": "#c1e0ff"
        },
        {
          "name": "Согласован старт",
          "sort": 40,
          "color": "#deff81"
        }
      ]
    }
  }
]
```

Then call:

```json
{
  "action": "create",
  "items": [
    {
      "name": "...",
      "is_main": false,
      "is_unsorted_on": true,
      "sort": 100,
      "_embedded": {
        "statuses": []
      }
    }
  ]
}
```

## Verification

After creation, call `amocrm_pipelines` with `action: get` and the returned `pipeline_id`.

Confirm:

- The pipeline exists.
- All expected status names exist.
- Each custom status has a color from `references/amocrm-status-colors.md`.
- The status order follows the real sales chronology.

## If amoCRM Rejects a Color

Replace it with a color from the whitelist and retry only the failed create/update operation. Preserve user data and do not delete pipelines unless the user explicitly asks.
