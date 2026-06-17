# Communication-Fact Pipeline Method

Source: https://introvert.bz/blog/tehniki-kak-uvelichit-vyruchku-cherez-voronku-prodazh/

Use the method when designing amoCRM pipeline statuses.

Core rules:

1. Name stages as completed facts in past tense. The source gives examples such as `получено`, `отправлен`, `согласован`, `передан`, `находится`.
2. Represent every external or internal customer-moving communication as a separate pipeline status.
3. When a manager performs an action that moves the deal forward, the manager must move the deal to the matching status.
4. The pipeline should expose bottlenecks and conversion losses between concrete actions.

Canonical example from the article:

`Получен новый лид -> Проведена квалификация -> Лид ушел на оценку -> Отправлено КП -> Ознакомлен с КП -> Проведена демонстрация -> Согласован старт -> Сформирован договор -> Согласован договор -> Передан в производство`

Other useful examples:

- B2B meetings: `Получен новый лид -> Проведена квалификация -> Назначена встреча -> Проведена встреча -> Согласован старт -> Согласован договор -> Успешно реализовано`
- Info-business/webinar: `Зарегистрировался на вебинар -> Пришел на вебинар -> Ознакомлен с продуктом -> Принял решение -> Успешно реализовано`
- Installation/services: `Получена новая заявка -> Назначен замер -> Осуществлен замер -> Утвержден проект -> Согласован старт -> Получена предоплата -> Окна установлены -> Успешно реализовано`

Rewrite vague statuses:

- `Новая заявка` -> `Получена новая заявка`
- `Квалификация` -> `Проведена квалификация`
- `КП` -> `Отправлено КП`
- `Договор` -> `Сформирован договор` or `Согласован договор`
- `Производство` -> `Передан в производство`

Do not use task-like names:

- `Позвонить`
- `Подготовить КП`
- `Ждем`
- `Думает`
- `В работе`
