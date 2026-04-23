# market_test — prediction markets research project

Проект: исследование Polymarket и альтернатив (Manifold, Limitless, Kalshi) с целью построить автоматизированную систему для paper-trading и, возможно позже, реальных ставок.

Пользователь: без нишевой экспертизы, бюджет ~$22 на тесты, юрисдикция РФ (Polymarket и Kalshi формально заблокированы). Deep context: `C:\Users\stas1\.claude\projects\D--ClaudeProjects-market-test\memory\` (MEMORY.md, research_findings.md).

## Платформа и окружение

- **OS**: Windows 11, shell: Git Bash (Unix syntax для путей: `/d/...`, forward slashes)
- **Python**: 3.11 через `py -3.11`. Python 3.14 тоже установлен, но на 3.11 гарантированно работают все колёса
- **Venv**: `.venv/` в корне. Активация не нужна — вызывай напрямую:
  ```bash
  ./.venv/Scripts/python.exe <script.py>
  ```
- **Кодировка вывода**: терминал cp1251. Для скриптов с юникодом ставь `PYTHONIOENCODING=utf-8` в запуск, либо вообще избегай спецсимволов (Δ, →, ≥) в `rich`-таблицах

## Структура проекта

```
polymarket_client.py    # read-only клиент Gamma API + CLOB prices-history
fetch_crypto_markets.py # скрипт: листинг топ крипто-маркетов по 24h volume
test_clob.py            # проверка CLOB эндпоинта (ad-hoc)
db.py                   # SQLite схема: markets, prices, sync_log. DB в data/polymarket.db
download_history.py     # загрузка истории в SQLite (фильтр по crypto + non-extreme YES price)
explore_db.py           # просмотр содержимого базы
requirements.txt        # requests, rich
data/polymarket.db      # локальная SQLite база (в .gitignore)
.venv/                  # Python 3.11 venv (в .gitignore)
```

## Основные команды

```bash
# Установка / обновление зависимостей
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# Листинг топ крипто-маркетов
./.venv/Scripts/python.exe fetch_crypto_markets.py

# Загрузка истории в SQLite (по умолчанию 15 маркетов, --no-crypto-filter для всех)
./.venv/Scripts/python.exe download_history.py -n 20

# Что лежит в базе
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe explore_db.py

# Быстрая проверка CLOB API
./.venv/Scripts/python.exe test_clob.py
```

## Архитектурные решения

- **SQLite без ORM**: маленький проект, sqlite3 stdlib хватает. Индексы — на `volume_24hr` и `(closed, active)`. Prices без rowid (PK = token_id+ts_unix).
- **Read-only клиент**: никаких приватных ключей, никакой торговли в Python-коде. Все торговые решения — явные, через CLI, с подтверждением.
- **Фильтр is_crypto**: regex с word boundaries (`\b(?:bitcoin|btc|ethereum|...)\b`) чтобы не матчить `eth` внутри `Netherlands`.
- **Manifold vs Polymarket**: Manifold — **play money**, используется для калибровки суждений (Brier score) и безопасного paper-trading. Polymarket — только чтение данных пока не доказан edge в paper trade.

## Правила безопасности (важно)

1. **НЕ торговать реальными деньгами** (Polymarket, Kalshi, Limitless) без явного подтверждения пользователя в этой же сессии. Manifold play money — свободно.
2. **НЕ писать приватные ключи / seed-фразы** в код, в репозиторий, в логи. Только через `.env` (который в `.gitignore`).
3. **НЕ обходить geoblock автоматически** (VPN-логика в коде). Если пользователь решит — он сделает это сам.
4. **Budget cap**: общий риск на реальные ставки ≤ 2000 RUB (~$22). Перед любой сделкой с реальными деньгами — подтвердить размер и остаток.
5. **Rate limits**: Gamma/CLOB не документируют жёсткие лимиты, но держи `time.sleep(0.3)` между запросами при массовой загрузке. Manifold: 500 req/min.

## Контекст для последующих итераций

**Этап A (готов)**: Polymarket data pipeline — клиент, SQLite, 15 маркетов × ~500 часовых точек. Загрузка занимает ~12 секунд.

**Этап B (в работе)**: Manifold paper trading. Пользователь делает аккаунт, потом получаем API-ключ → `.env` → клиент → скрипт ставок на play money.

**Этап C (планируется)**: Анализ конкретного маркета — orderbook, whale positions. Вероятно через CLOB `/book/<token_id>` и Polygon-блокчейн события.

**Следующее после C**: бэктест-фреймворк поверх накопленной истории. Строим конкретную гипотезу (например, mean reversion на multi-day BTC markets), прогоняем на прошлых данных, смотрим Sharpe / max drawdown.

## Важные ограничения и факты

- **71% пользователей Polymarket теряют деньги** (SSRN Akey et al. 2026)
- **Latency arb** между Polymarket↔Kalshi закрыт для retail (окна <3с, боты <100мс)
- **Dynamic taker fees** (до 3.15%) на 15-мин крипто-маркетах убили эту нишу
- **Россия в OFAC-блоке** Polymarket и Kalshi. Legal access через эти платформы нет
- Комиссии taker: Crypto 1.80%, Politics 1.00%, Sports 0.75%, Geopolitics 0%

## Когда сомневаешься

- Неизвестный API-эндпоинт → сначала `test_*.py` ad-hoc скрипт, посмотри ответ, потом строй логику
- Много кода для простой задачи → переосмысли, скорее всего overengineering
- Юзер просит «что-то простое» → предлагай бесплатное / play money / paper trade в первую очередь
- Новый MCP-сервер в настройки → по умолчанию НЕ ставить, обсудить с юзером ценность
