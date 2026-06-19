# infrastructure

**Русский** · [English](README.en.md)

Источник правды для рантайма **Solid Stats** — статистики игр сообщества
[Solid Games](https://sg.zone) (ArmA 3). Владеет стейджинг-окружением в
Kubernetes (k3s): манифестами `k8s/staging/`, рантайм-обвязкой (секреты, env,
сетевая изоляция), скриптами деплоя и операционными ранбуками, расписанием
бэкапов PostgreSQL в S3 и наблюдаемостью.

Часть многорепной платформы: бэкенд и источник правды — в `server-2`, поиск
сырых реплеев — в `replays-fetcher`, парсинг OCAP — в `replay-parser-2`,
веб-интерфейс — в `web`. infrastructure — слой, где их образы собираются в
работающий рантайм. Сами образы и исходный код принадлежат своим репозиториям;
здесь — только то, как они связаны в стейджинге.

> Solid Stats от и до строят AI-агенты по процессу
> [GSD](https://github.com/open-gsd/gsd-core). Разработка вне GSD — вне процесса.

## Быстрый старт

Проверка манифестов, скриптов и структуры рендеримых секретов перед деплоем:

```bash
python3 scripts/validate-staging.py
```

Деплой идёт в CI при пуше в `master` (или вручную через `workflow_dispatch`):
открывается SSH-форвард к закрытому API k3s, из токена ServiceAccount
`ci-deployer` собирается kubeconfig, применяется `k8s/staging/`. Ручной бэкап
после применения манифестов:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

Секреты приходят из GitHub environment на момент деплоя и не хранятся в git.

## Документация

- [docs/deploy.md](docs/deploy.md) — модель деплоя, состав v1, граница владения
- [docs/staging.md](docs/staging.md) — операции стейджинга и Staging Handoff Matrix
- [docs/backup-restore.md](docs/backup-restore.md) — бэкап и восстановление PostgreSQL
- [docs/k3s-api-access.md](docs/k3s-api-access.md) — доступ к API k3s с рабочей станции
- [docs/observability.md](docs/observability.md) · [docs/glitchtip.md](docs/glitchtip.md) — наблюдаемость
- остальные ранбуки — в [docs/](docs/); продуктовый контекст и состояние (GSD) — в `.planning/`

## Стек

Kubernetes (k3s) · PostgreSQL · RabbitMQ · Timeweb S3 · GitHub Actions · Bash · Python 3

## Лицензия — [MIT](LICENSE)
