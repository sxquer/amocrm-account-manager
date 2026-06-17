# amoCRM MCP

MCP-сервер для управления аккаунтом amoCRM через API v4 с долгосрочным токеном. OAuth 2.0, refresh token и обмен кодов здесь намеренно не используются.

## Codex plugin

Проект оформлен как Codex-плагин:

```text
.codex-plugin/plugin.json
.mcp.json
skills/
amocrm_mcp/
scripts/
```

Плагин содержит MCP-сервер `amocrm` и skills для предметной настройки аккаунтов.

Первый skill:

- `amocrm-create-pipelines` — создает воронки amoCRM по методологии `коммуникация-факт`: статусы называются фактами совершенных действий в прошедшем времени, а каждому пользовательскому статусу задается цвет из официального whitelist amoCRM.

Секреты не хранятся в plugin manifest. Перед запуском MCP нужны переменные:

```bash
export AMOCRM_BASE_URL="https://example.amocrm.ru"
export AMOCRM_LONG_LIVED_TOKEN="your-long-lived-token"
```

## Что покрыто

- Аккаунт: `/api/v4/account`.
- Основные сущности: сделки, контакты, компании, покупатели, задачи, пользователи, роли, события, вебхуки, виджеты, источники, беседы, шаблоны чатов.
- Воронки, этапы и причины отказа.
- Поля и группы полей.
- Теги, примечания и связи сущностей.
- Каталоги/списки и элементы каталогов.
- Транзакции покупателей.
- Неразобранное, короткие ссылки, звонки и другие специальные методы через `amocrm_resource_action`.
- Любые новые или редкие методы amoCRM через `amocrm_api_request`, если путь начинается с `/api/...`.

## Настройка

Минимальный вариант:

```bash
export AMOCRM_SUBDOMAIN="example"
export AMOCRM_LONG_LIVED_TOKEN="your-long-lived-token"
python -m amocrm_mcp
```

Или явно:

```bash
export AMOCRM_BASE_URL="https://example.amocrm.ru"
export AMOCRM_LONG_LIVED_TOKEN="your-long-lived-token"
python -m amocrm_mcp
```

Для глобальной зоны можно использовать:

```bash
export AMOCRM_SUBDOMAIN="example"
export AMOCRM_DOMAIN_SUFFIX="amocrm.com"
```

Опционально:

```bash
export AMOCRM_TIMEOUT="30"
```

## Локальный env проекта

Если в рабочей папке проекта или в одной из родительских папок есть `.env` или `.amocrm.env`, MCP загружает из него `AMOCRM_*` настройки и они имеют приоритет над env, переданным MCP-клиентом.

Пример `.env`:

```bash
AMOCRM_BASE_URL=https://example.amocrm.ru
AMOCRM_LONG_LIVED_TOKEN=your-long-lived-token
AMOCRM_READONLY=true
AMOCRM_WRITE_ALLOWLIST=tasks,notes
AMOCRM_RATE_LIMIT_SECONDS=1
```

Загружаются только переменные с префиксом `AMOCRM_`; остальные строки игнорируются. Можно указать явный путь:

```bash
AMOCRM_ENV_FILE=/absolute/path/to/.amocrm.env
```

Файлы `.env` и `.amocrm.env` добавлены в `.gitignore`, потому что обычно содержат токены.

Все HTTP-запросы к amoCRM проходят через общий лимитер. По умолчанию сервер делает не чаще одного запроса в секунду, включая MCP tools, пагинацию и локальные scripts:

```bash
export AMOCRM_RATE_LIMIT_SECONDS="1"
```

Лимитер межпроцессный: несколько параллельных запусков используют общий lock-файл в temp-директории. Для тестов можно отключить ожидание:

```bash
export AMOCRM_RATE_LIMIT_SECONDS="0"
```

## Безопасный режим записи

Можно запретить любые изменения в аккаунте:

```bash
export AMOCRM_READONLY="true"
```

В этом режиме MCP выполняет только `GET`. Любые `POST`, `PATCH`, `DELETE` блокируются до HTTP-запроса, включая `amocrm_api_request`, `amocrm_batch_request`, scripts и специализированные tools.

Можно разрешить запись только в отдельные ресурсы:

```bash
export AMOCRM_WRITE_ALLOWLIST="tasks,notes"
```

Тогда, например, задачи и примечания можно менять, а сделки, воронки, поля, вебхуки и остальные ресурсы нельзя.

Можно точечно запретить опасные ресурсы:

```bash
export AMOCRM_WRITE_DENYLIST="pipelines,pipeline_statuses,custom_fields,custom_field_groups"
```

Такой режим позволяет продолжать менять задачи или сделки, но запрещает менять/удалять воронки, этапы и поля.

Поддерживаемые имена ресурсов в политике: `leads`, `contacts`, `companies`, `customers`, `tasks`, `pipelines`, `pipeline_statuses`, `custom_fields`, `custom_field_groups`, `tags`, `notes`, `links`, `catalogs`, `catalog_elements`, `customer_transactions`, `users`, `roles`, `webhooks`, `sources`, `unsorted`, `events`, `widgets`, `conversations`, `short_links`, `calls`, `chat_templates`.

### Security disclaimer

`AMOCRM_READONLY`, `AMOCRM_WRITE_ALLOWLIST` и `AMOCRM_WRITE_DENYLIST` — это защитные ограничения внутри этого MCP-сервера, а не полноценная security boundary.

Если агенту доступен write-capable amoCRM token локально — в env, `.env`, Codex config, shell history, keychain, Docker secret, логах или файлах проекта — агент с доступом к shell/файловой системе теоретически может обойти MCP и вызвать amoCRM API напрямую. Локальный READONLY-режим защищает только официальный путь через MCP.

Строгий вариант для read-only или ограниченного write-доступа:

```text
Codex / local MCP
  не хранит amoCRM token
  обращается только к remote gateway

Remote gateway
  хранит amoCRM token
  применяет READONLY / allowlist / denylist policy
  проксирует только разрешенные запросы
  пишет audit log

amoCRM API
```

В такой схеме локально хранится только gateway-token с ограниченными возможностями. Настоящий amoCRM token не покидает удаленный gateway и не возвращается агенту. Это единственный надежный способ не дать локальному агенту использовать write-token в обход MCP.

## Подключение к MCP-клиенту

Пример конфигурации:

```json
{
  "mcpServers": {
    "amocrm": {
      "command": "python",
      "args": ["-m", "amocrm_mcp"],
      "env": {
        "AMOCRM_BASE_URL": "https://example.amocrm.ru",
        "AMOCRM_LONG_LIVED_TOKEN": "your-long-lived-token"
      }
    }
  }
}
```

## Инструменты

- `amocrm_config_check` проверяет, видит ли сервер домен и токен, не раскрывая сам токен.
- `amocrm_describe_capabilities` показывает карту ресурсов и действий.
- `amocrm_get_account` получает параметры аккаунта.
- `amocrm_list_entities`, `amocrm_get_entity`, `amocrm_create_entities`, `amocrm_update_entities`, `amocrm_update_entity` работают с верхнеуровневыми коллекциями.
- `amocrm_batch_create_entities` создает много сущностей пачками, автоматически режет массив на чанки и соблюдает общий лимитер запросов.
- `amocrm_batch_request` отправляет большие `POST`/`PATCH` array payloads в любой `/api/...` endpoint чанками.
- `amocrm_entity_notes`, `amocrm_entity_links`, `amocrm_entity_tags` управляют заметками, связями и тегами.
- `amocrm_custom_fields`, `amocrm_pipelines`, `amocrm_catalog_elements`, `amocrm_customer_transactions` закрывают специальные разделы.
- `amocrm_resource_action` вызывает действие из встроенной карты amoCRM-ресурсов.
- `amocrm_api_request` вызывает любой разрешенный `/api/...` путь на настроенном аккаунте.
- `amocrm_paginate` собирает несколько страниц GET-коллекции.

## Примеры

Получить аккаунт с группами и типами задач:

```json
{
  "with": ["users_groups", "task_types", "datetime_settings", "version"]
}
```

Найти сделки:

```json
{
  "entity_type": "leads",
  "params": {
    "query": "Иван",
    "limit": 50,
    "with": "contacts"
  }
}
```

Создать контакт:

```json
{
  "entity_type": "contacts",
  "items": [
    {
      "name": "Иван Петров",
      "custom_fields_values": [
        {
          "field_code": "PHONE",
          "values": [{ "value": "+79990000000", "enum_code": "WORK" }]
        }
      ]
    }
  ]
}
```

Вызвать редкий метод напрямую:

```json
{
  "method": "GET",
  "path": "/api/v4/leads/pipelines",
  "params": { "limit": 250 }
}
```

Массово создать задачи пачками:

```json
{
  "entity_type": "tasks",
  "chunk_size": 50,
  "items": [
    {
      "text": "Связаться с клиентом",
      "complete_till": 1819756800,
      "entity_id": 123,
      "entity_type": "leads"
    }
  ]
}
```

Для сценариев вроде "создай 20 сделок и задачи в них" используйте batch-подход: сначала `amocrm_batch_create_entities` для сделок, затем `amocrm_batch_create_entities` для задач с `entity_id` созданных сделок. Пример готового сценария лежит в `scripts/create_test_leads_with_tasks.py`.

## Документация amoCRM, по которой собран сервер

- https://www.amocrm.ru/developers/content/crm_platform/api-reference
- https://www.amocrm.ru/developers/content/oauth/step-by-step
- https://www.amocrm.ru/developers/content/crm_platform/account-info
- https://www.amocrm.ru/developers/content/crm_platform/leads-api
- https://www.amocrm.ru/developers/content/crm_platform/contacts-api
- https://www.amocrm.ru/developers/content/crm_platform/companies-api
- https://www.amocrm.ru/developers/content/crm_platform/tasks-api
- https://www.amocrm.ru/developers/content/crm_platform/custom-fields

## Важные замечания

Долгосрочный токен имеет права пользователя, который выдал доступ. Если amoCRM вернет 401/403, это обычно означает истекший/отозванный токен или нехватку прав у пользователя.

Некоторые методы amoCRM зависят от тарифа, прав, включенных функций аккаунта и конкретной зоны (`amocrm.ru` или `amocrm.com`). Для таких случаев используйте `amocrm_api_request`: сервер не ограничивает функциональность жестким списком старых методов.
