# Cross-source dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Подтверждать межисточниковые повторы по исходной вакансии и показывать объяснимые предположения без скрытия.
**Architecture:** Отдельный модуль сопоставления готовит архивные записи в памяти. Store сохраняет их атомарно с журналом; main связывает сбор, отбор и письмо.
**Tech Stack:** Python, SQLite, BeautifulSoup, unittest; без новых зависимостей.
**Spec:** docs/superpowers/specs/2026-11-19-cross-source-dedup-design.md (утверждён пользователем 19.11).

## Global Constraints

- Старые ledger keys/code/status не переписывать миграцией; applied/reviewed без ограничения возраста.
- Смысловое окно 10 дней, точное 30 дней; смысловые предположения не скрывают карточки.
- Запись состояния только после успешной отправки/пустого выпуска; dry-run и SMTP failure без архива.
- Наблюдать минимум шесть успешных штатных выпусков, без автоматического включения смыслового скрытия.
- Реализовать самостоятельно в ветке feat/cross-source-dedup; без дополнительных разрешений на уже утверждённую работу.

## Review Focus

- Несколько вакансий в посте и несколько исходных ссылок: не объединять неоднозначное.
- Старые отметки и отметки текущего запуска: статус блокирует повтор подтверждённой вакансии.
- Старый архив за пределами окна: повтор не обновляет первое наблюдение для смыслового поиска.
- Общие шаблоны, контакты и разные команды/ID: не становятся идентичностью.
- Откат транзакции и ошибки обогащения: не теряются исходные карточки и состояние.

### Task 1: Подтверждение и пометки

**Files:** Create vd/duplicates.py, tests/test_duplicates.py; Modify vd/models.py, vd/classify.py.
**Interfaces:** analyze(verdicts, history, now, exact_days=30) -> list[dict] архивных публикаций; identity(url) -> str; Verdict получает ссылки источников и possible_duplicate.
- [x] Написать тесты пары Avito 20883, разных ID, неоднозначных ссылок и команды качества; увидеть RED.
- [x] Добавить извлечение конкретных URL/ID с пространством имён, выбор представителя и консервативную пометку содержательных описаний.
- [x] Проверить независимость порядка источников, окна и отсутствие смыслового переноса отметок; GREEN.

### Task 2: Архив и совместимость

**Files:** Modify vd/store.py; Test tests/test_duplicates.py.
**Interfaces:** Store.duplicate_history(marks=None) -> list[dict]; commit_after_send(..., publications=None) сохраняет пакет в общей транзакции; duplicate_observation_count() считает штатные успешные выпуски.
- [x] RED: перезапуск архива, старые коды, связанная отметка после 30 дней, rollback, отдельные вакансии подборки.
- [x] Добавочные таблицы сущностей/публикаций/отправок/предположений. История отправок сохраняет старые коды и статусы.
- [x] GREEN: миграция повторяема, first_seen не продлевается, integrity_check OK.

### Task 3: Обогащение и pipeline

**Files:** Modify vd/sources/jabka.py, main.py, vd/digest.py; Test tests/test_duplicates.py.
**Interfaces:** jabka.enrich(items, fetch, limit=20) -> list[str] предупреждений; analyze вызывается после классификации, перед существующим дедупом, архивируется в обеих успешных ветках.
- [x] RED: полная карточка работодателя, ограничение запросов/ошибки, HTML/text пометки, successful/empty/failed/dry-run.
- [x] Добавить обогащение конкретных jabka карточек до классификации, источники/пометки в обеих версиях письма; статистику и счётчик наблюдения.
- [x] GREEN: полный unittest набор и проверочный pipeline на копии SQLite, отправка заблокирована.

### Task 4: Проверка и документация

**Files:** README.md, ARCHITECTURE.md, memory.md, дизайн/план.
- [x] Финальное независимое ревью (executing-plans/requesting-code-review), важные исправления RED→GREEN.
- [x] Проверить весь набор, diff --check, копию рабочей SQLite с прежними кодами/статусами. Рабочую базу не менять исследовательскими командами.
- [x] Записать результаты и ограничения наблюдения; сообщить пользователю реализованное поведение без утверждений о ещё не прошедших шести выпусках.

## Execution ledger

- Baseline: 231 tests OK (19.11, elevated Python).
- Ruling: отдельная ветка в текущей папке вместо нового worktree — сохраняет доступ к установленной .venv и локальным фикстурам; main остаётся исходной точкой.
- Pre-flight: analyze возвращает publications для commit_after_send; digest читает поля Verdict. Интерфейсы согласованы.
- Tasks 1–3: complete. Новые тесты наблюдались RED до реализации соответствующих интерфейсов, затем GREEN; копия SQLite подтверждает сохранность 332 старых ledger-строк и атомарность dry-run.
- Final review: отдельный reviewer проверил код, работа прерывалась временным лимитом сервиса и затем была продолжена тем же reviewer. Все пять Important замечаний исправлены с RED→GREEN: weak ID bridge, listing URL, multiple jobs in one post, expired exact-URL entity binding, explicit employer format restriction.
- Дополнительные регрессии RED→GREEN: перенос группы целиком, разные грейды, шаблон условий без двоеточия, старые коды после повторной отправки, сохранение старого ledger при архивации.
- Final: minor (deferred): среди нескольких подходящих смысловых кандидатов выбирается первый по порядку, а не максимальное сходство; это влияет на ссылку в пометке, но не скрывает вакансии и не переносит отметки.
- Ruling: проверочный pipeline использует реальные публичные тексты и копию SQLite с заменёнными сетью/SMTP — исключает настоящую рассылку; доступность всех источников по сети этим прогоном не проверяется.
- Task 4: complete. Final suite: 262 tests OK, 12.196 s (231 прежних + 31 новая регрессия), out/dedup-tests.txt. Copy validation: old_ledger_rows=332 unchanged, dry_run unchanged, archived_publications=2, integrity/FKs OK, out/duplicates-validation/summary.json. git diff --check без ошибок. Наблюдение будущих шести штатных выпусков ещё не выполнено.
