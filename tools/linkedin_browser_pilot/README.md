# LinkedIn browser pilot

Экспериментальный контроллер для ручной проверки поиска LinkedIn. Не подключён к main.py,
планировщику, SMTP или Store. Использует установленный Google Chrome в видимом режиме,
с отдельным профилем и включённой песочницей. Вход выполняет пользователь.

Из корня проекта (установка только в игнорируемый out/, без изменения .venv):

```powershell
.venv/Scripts/python.exe -m pip install --index-url https://pypi.org/simple --target out/linkedin-browser-playwright/packages -r tools/linkedin_browser_pilot/requirements.txt
.venv/Scripts/python.exe tools/linkedin_browser_pilot/browser_session.py
```

Контроллер открывает LinkedIn и остаётся запущенным. Все локальные данные находятся в
`out/linkedin-browser-playwright/`: `profile/`, `status.json`, `command.json`, `response.json`.
Пароли, cookies и storage не извлекаются; profile/ не копировать в Git или передачу контекста.
Перед запуском убедиться, что другой контроллер не использует этот профиль, а в command.json
не осталась старая команда close. Профиль не удалять: он хранит ручной вход.

Команды — JSON в command.json; каждый запрос получает новый непустой id. Пример:

```json
{"id":"state-001","action":"state"}
```

`state` возвращает только URL/заголовки вкладок. `search` принимает url только на
`https://www.linkedin.com/search/results/content/`. `read_results` читает текст и видимые ссылки
только в main страницы поиска, не на странице входа или в ленте. `close` завершает контроллер.
Ждать response.json с совпадающим id; старый ответ не означает выполнения новой команды.

Формат поиска, проверенный вручную:

```text
https://www.linkedin.com/search/results/content/?keywords=%23productanalyst&datePosted=%22past-week%22&sortBy=%22date_posted%22
```

Один прогон не доказывает устойчивость фоновой автоматизации. Раскрытие постов, постоянные
URL/ID, дедуп и регулярный сбор не реализованы. Не вводить авторизацию программно, не обходить
капчу/защиту, не использовать основной профиль Chrome. Закрытие окна пользователем может
завершить контроллер с ошибкой; перед повтором проверить status.json и stderr.
