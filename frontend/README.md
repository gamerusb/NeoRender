# NeoRender Pro — UI (React)

Сборка подключается к уже запущенному API (`uvicorn api_server:app`).

## Разработка

```bash
cd frontend
npm install
npm run dev
```

Откройте `http://127.0.0.1:5173/ui/#/dashboard` (префикс `/ui/`, маршруты — hash). Запросы `/api` и `/ui/legacy` проксируются на `http://127.0.0.1:8765`.

## Продакшен

```bash
cd frontend
npm install
npm run build
```

Артефакты попадают в `web/dist/`. После перезапуска API корень интерфейса: `http://127.0.0.1:8765/ui/` (React). Классический одностраничный UI доступен по `…/ui/legacy/` (используется в iframe для разделов вне дашборда).

Без `web/dist` сервер отдаёт только `web/legacy/` на `/ui`, как до миграции.
