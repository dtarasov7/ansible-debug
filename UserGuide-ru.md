# Руководство пользователя `inspect_step`

[English](UserGuide.md) | [Русский](UserGuide-ru.md)

В этом руководстве описаны установка, повседневное использование, просмотр переменных, изменение значений во время выполнения, безопасность и диагностика проблем для `inspect_step` версии 2.0.0.

## 1. Назначение

`inspect_step` — custom strategy plugin для интерактивной отладки Ansible. Он останавливается до постановки исполняемой task в очередь, показывает, что будет запущено, и позволяет оператору исследовать контекст task до выбора действия.

Плагин полезен, когда требуется:

- понять, какая task сейчас будет выполнена;
- явно посмотреть результат одной task, обычно защищённой task-level `no_log`;
- сравнить переменные нескольких hosts, выбранных через `--limit`;
- исследовать facts, переменные role, зарегистрированные результаты и значения `set_fact`;
- посмотреть исходные и templated-аргументы task;
- вычислить составную Jinja-строку с переменными выбранного host;
- предварительно проверить conditions, сравнить выражения между hosts и посмотреть прошлые результаты;
- раскрыть host-specific items loop и посмотреть metadata loop-control;
- посмотреть дерево tasks/includes текущего play и выбрать точный breakpoint по ID task;
- отслеживать выбранные выражения и выполнять до breakpoint по task, role или tag;
- отрендерить источник `ansible.builtin.template` до выполнения и посмотреть или сохранить результат;
- сократить вывод очень больших вложенных структур переменных;
- временно переопределить переменную без редактирования inventory или playbook;
- пропустить одну task или продолжить остаток play без обычных остановок task.

Плагин расширяет штатную стратегию Ansible `linear`. Обработка inventory, precedence переменных, templating, выполнение task, handlers, loops, conditions, delegation, tags и результатов остаются в штатных механизмах Ansible.

## 2. Поддерживаемое окружение

Диапазон технической совместимости:

```text
ansible-core >= 2.12.0, < 2.14
```

Основная протестированная версия — `ansible-core 2.13.13`. Плагин использует внутренние strategy API, совместимость которых Ansible не гарантирует.

При запуске plugin проверяет обнаруженную версию `ansible-core`:

- 2.12 и 2.13 продолжают работу с выводом статуса совместимости;
- версии ниже 2.12 продолжают работу с явным warning о неполной совместимости, поскольку просмотр переменных task может быть недоступен;
- версии 2.14 и новее сразу завершают работу с сообщением о несовместимости и рекомендацией установить 2.12 или 2.13.

Python должен быть совместим с установленным выпуском Ansible. Стандартный Python-модуль `readline` необязателен: он нужен только для интерактивной истории и редактирования строки клавишами управления курсором.

## 3. Модель выполнения

Для каждой lockstep-task плагин определяет активные hosts и выбирает первый из них как host просмотра по умолчанию. После этого он:

1. получает переменные task через Ansible `VariableManager`;
2. выводит имя task и host-контекст;
3. отображает исходное определение task с маскированием распространённых ключей секретов;
4. вычисляет настроенные watches и открывает цикл команд `inspect-step>`;
5. ожидает `run`, `run!`, `skip`, `go` или `continue`;
6. передаёт постановку task в очередь и её выполнение унаследованной стратегии `linear`;
7. сохраняет обработанный результат каждого host для просмотра в последующем prompt.

Если выполненная task возвращает необработанную ошибку, plugin открывает отдельный prompt `inspect-failure>` до того, как Ansible окончательно исключит failed hosts из оставшейся части play. Оператор может явно считать ошибку проигнорированной или сохранить штатное failed-состояние.

При нескольких активных hosts prompt появляется один раз для lockstep-task, а не отдельно для каждого host. Команда `run` выполняет task для активной группы hosts в соответствии со штатным поведением `linear`.

## 4. Установка

Поместите plugin в каталог strategy plugins внутри Ansible-проекта:

```text
project/
├── ansible.cfg
├── inventory
├── playbook.yml
└── strategy_plugins/
    └── inspect_step.py
```

Настройте каталог в `ansible.cfg`:

```ini
[defaults]
strategy_plugins = ./strategy_plugins
```

Относительный путь вычисляется от каталога, из которого запускается `ansible-playbook`. Если Ansible запускается из другого каталога, укажите корректный относительный или абсолютный путь.

Выберите стратегию в play:

```yaml
---
- name: Debug application deployment
  hosts: web
  strategy: inspect_step

  roles:
    - application
```

## 5. Запуск интерактивного режима

Используйте plugin вместе с параметром Ansible `--step`:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --step
```

Отладка одного host — наиболее простой режим, поскольку facts, inventory variables, зарегистрированные результаты и runtime facts могут отличаться между hosts.

Для отладки группы или нескольких hosts:

```bash
ansible-playbook -i inventory playbook.yml --limit 'web01,web02' --step
```

или:

```bash
ansible-playbook -i inventory playbook.yml --limit web --step
```

При инициализации стратегии один раз на процесс `ansible-playbook` выводится строка:

```text
inspect_step version 2.0.0
Ansible compatibility: ansible-core 2.13.13 is the primary tested version (technical range 2.12-2.13).
```

Без `--step` стратегия ведёт себя как `linear` и не открывает prompt inspector. Версия и статус совместимости всё равно отображаются при инициализации стратегии.

## 6. Prompt и предварительный просмотр task

Обычная остановка выглядит так:

```text
INSPECT TASK: application : Configure service
Host: web01 (inspection host; task has 2 active hosts)

TASK SOURCE [/project/roles/application/tasks/main.yml:12] (secrets masked)
- name: Configure service
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/app.conf

inspect-step>
```

В момент появления prompt task ещё не выполнена. Предварительный просмотр строится из разобранных Ansible данных task. Разметка YAML, кавычки и отступы могут отличаться от исходного файла, а исходные комментарии не сохраняются.

У неявных task, например `Gathering Facts`, исходные разобранные данные могут отсутствовать. В таком случае следующее warning ожидаемо и не влияет на выполнение:

```text
[WARNING]: Original task definition is unavailable
```

## 7. Сводка команд

| Команда | Назначение | Маскирование секретов |
|---|---|---|
| `r`, `run` | Выполнить текущую task | Не применяется |
| `r!`, `run!` | Выполнить текущую task с отключённым task-level `no_log` | Намеренно отключено |
| `ra`, `run-all` | Выполнить dynamic include и всех потомков, затем вернуть остановки task | Не применяется |
| `s`, `skip` | Пропустить текущую task | Не применяется |
| `c`, `continue` | Выполнить task и отключить последующие обычные остановки task | Не применяется |
| `g`, `go` | Выполнять tasks до совпадения с настроенным breakpoint | Не применяется |
| `w` | Повторно показать исходное определение task | Включено |
| `hosts` | Показать hosts play после inventory и `--limit` | Не применяется |
| `vars`, `v`, `var` + `[NAME\|PATH\|glob=PATTERN\|regex=REGEXP\|JINJA_EXPRESSION] [host=HOST] [depth=N]` | Показать variables или вычислить выражение | Эвристическое; вычисленный скаляр может раскрыть секрет |
| `vars!`, `v!`, `var!` + `[NAME\|PATH\|glob=PATTERN\|regex=REGEXP\|JINJA_EXPRESSION] [host=HOST] [depth=N]` | Аналогичная команда без маскирования | Намеренно отключено |
| `set NAME YAML_VALUE [host=HOST]` | Изменить top-level переменную в памяти | Значение не повторяется |
| `e JINJA_EXPRESSION [host=HOST]` | Вычислить составную Jinja-строку; alias для `eval` | Отключено |
| `eval JINJA_EXPRESSION [host=HOST]` | Вычислить составную Jinja-строку с отключёнными lookups | Отключено |
| `eval-lookup JINJA_EXPRESSION [host=HOST]` | Один раз вычислить выражение для одного host с включёнными lookups Ansible | Отключено |
| `eval-all JINJA_EXPRESSION [diff=true]` | Вычислить выражение для всех активных hosts текущей task | Отключено |
| `when [HOST\|all]` | Вычислить conditions текущей task до выполнения | Не применяется |
| `loop [HOST\|all] [depth=N]` | Показать элементы loop и metadata loop-control | Включено |
| `loop! [HOST\|all] [depth=N]` | Показать элементы loop без маскирования | Намеренно отключено |
| `loop eval ITEM EXPRESSION [host=HOST]` | Вычислить Jinja-expression в контексте выбранного item | Отключено |
| `loop when ITEM [host=HOST]` | Вычислить conditions task для выбранного item | Не применяется |
| `loop args ITEM [host=HOST]` | Показать templated-аргументы для выбранного item | Включено |
| `loop template ITEM [host=HOST]` | Отрендерить template для выбранного item | Намеренно отключено |
| `result [HOST\|all] [depth=N]` | Показать результат предыдущей выполненной task | Включено |
| `result! [HOST\|all] [depth=N]` | Показать предыдущий результат без маскирования | Намеренно отключено |
| `watch add EXPRESSION [host=HOST]` | Добавить выражение для вывода на каждой остановке | Отключено |
| `watch list`, `watch delete ID` | Показать или удалить watches | Не применяется |
| `tasks [tree] [host=HOST] [regex=REGEXP] [role=NAME] [tag=TAG]` | Показать статически известные и runtime-раскрытые tasks | Не применяется |
| `break pick TASK_ID` | Добавить точный breakpoint для записи task-browser | Не применяется |
| `break task REGEX` | Остановить `go` при regexp-совпадении имени task | Не применяется |
| `break role NAME`, `break tag TAG` | Остановить `go` при точном совпадении role или tag | Не применяется |
| `break list`, `break delete ID` | Показать или удалить breakpoints | Не применяется |
| `a`, `args` | Показать templated-аргументы task | Включено |
| `args!` | Показать templated-аргументы task | Намеренно отключено |
| `raw` | Показать исходные `task.args` | Отключено |
| `template [HOST]` | Отрендерить текущую template-task и показать результат | Намеренно отключено |
| `template-save LOCAL_PATH [HOST]` | Отрендерить и сохранить результат на controller | Намеренно отключено |
| `h`, `help`, `?` | Показать встроенную справку | Не применяется |

У failure prompt есть собственные команды:

| Команда | Назначение |
|---|---|
| `i`, `ignore` | Игнорировать ошибки текущей task и сохранить текущую настройку step mode |
| `c`, `continue` | Игнорировать ошибки текущей task и отключить последующие обычные остановки |
| `a`, `abort` | Сохранить штатное failed-поведение Ansible для затронутых hosts |

Неизвестная команда inspector или ошибка диагностической операции не завершает playbook. Inspector остаётся на текущей task и ожидает следующую команду. Это не означает, что ошибка выполненной Ansible task игнорируется автоматически: она должна быть обработана в playbook или явно принята через `inspect-failure>`.

## 8. Управление выполнением task

### Выполнение текущей task

```text
inspect-step> r

RUN: application : Configure service
```

`run` эквивалентна `r`. Пока step mode остаётся включённым, следующая исполняемая task снова откроет prompt.

### Выполнение с отключённым task-level `no_log`

```text
inspect-step> r!

[WARNING]: task-level no_log is disabled for this task; results and secrets may
be written to stdout and callback logs

RUN (no_log disabled): application : Read protected value
```

`run!` эквивалентна `r!`. Переопределение применяется ко всем активным hosts и items loop выбранной task. Inspector ставит в очередь копию с тем же UUID и `no_log: false`; исходная task и `no_log` последующих tasks не изменяются.

Команда обходит только task-level `no_log`. Модуль может независимо маскировать аргументы, помеченные `no_log` в его argument specification; такие значения могут остаться заменёнными на `VALUE_SPECIFIED_IN_NO_LOG_PARAMETER`. Controller-wide настройка `DEFAULT_NO_LOG` также находится вне этого task-level переопределения. После `r!` считайте вывод терминала, callback plugins, job logs и сохранённые events содержащими секреты.

### Полное выполнение dynamic include

В prompt `include_tasks` или `include_role` используйте `ra` или `run-all`, чтобы выполнить dynamic include и всё его дерево потомков без промежуточных prompts task:

```text
inspect-step> ra

RUN ALL: application : Load platform tasks
```

Вложенные dynamic includes и loops include остаются внутри выбранной области. Handlers, синхронно вызванные через `flush_handlers` внутри области, также выполняются без prompt task. Первая исполняемая task за пределами include выводит `RUN ALL COMPLETE` и снова открывает обычный prompt. Breakpoints и watches внутри области не останавливают выполнение, поскольку обычные prompts там не открываются; необработанная ошибка всё ещё может открыть `inspect-failure>`.

Существующие команды сохраняют значение в prompt dynamic include: `s` пропускает весь include до его раскрытия, а `r` раскрывает его и затем останавливается на каждой подключённой task. `run-all` отклоняется для обычных tasks и статических `import_tasks` или `import_role`.

### Пропуск текущей task

```text
inspect-step> s

SKIP: application : Restart service
```

`skip` эквивалентна `s`. Для lockstep-task действие пропускает task для текущей активной группы hosts.

Inspector открывает один prompt выбора для каждой явной task `ansible.builtin.meta`, хотя ansible-core обычно исключает meta-actions из `--step`. Одно решение применяется ко всей активной lockstep-группе hosts: `r` выполняет action с её штатной семантикой Ansible, а `s` пропускает её для группы. Например, пропуск `end_play` переходит к следующей task, а выполнение завершает play. Неявные tasks `noop`, `flush_handlers` и `role_complete`, созданные Ansible, остаются скрытыми и выполняются штатно.

### Продолжение без следующих обычных остановок task

```text
inspect-step> c

RUN: application : Configure service
```

`continue` эквивалентна `c`. Текущая task выполняется, а остаток play проходит без обычных остановок просмотра task. При необработанной ошибке post-failure prompt всё ещё может появиться, чтобы оператор решил, должны ли затронутые hosts продолжить выполнение.

### Выполнение до breakpoint

Сначала просмотрите tasks, если их имена, roles или структура includes заранее неизвестны:

```text
tasks
tasks tree
tasks tree host=web02 role=application
tasks regex='(?i)configure|restart'
tasks tag=deployment
break pick 12
go
```

`tasks` назначает стабильные в пределах текущего play числовые ID и показывает состояние `CURRENT`, `REACHED` или `PENDING` для выбранного inspection host. `REACHED` означает, что iterator дошёл до task, включая пропущенную в inspector task, но не подтверждает успешное выполнение. `host=HOST` выбирает этот status-view, но не может заранее вычислить будущие conditions `when` или зависящие от host dynamic includes. Вариант `tree` сохраняет скомпилированную вложенность roles и includes. При фильтрации дерева вместе с совпавшими tasks остаются их include-предки, чтобы контекст не терялся. `regex` использует Python substring search; `role` и `tag` проверяются точным регистрозависимым совпадением.

Статические imports и roles компилируются до запуска strategy, поэтому их потомки видны сразу. Синтетическая import-группа помечена `static import; group only`; установить breakpoint на неё нельзя, поскольку runtime-остановки на этом узле не существует. Узлы dynamic `include_tasks` и `include_role` помечены `dynamic; not expanded`, а их потомки добавляются в это же дерево после раскрытия Ansible. До этого runtime-ID дочерних tasks ещё не существуют.

`break pick TASK_ID` привязывается к внутреннему runtime UUID выбранной task, а не к её отображаемому имени. Это различает одинаково названные tasks и является самым точным способом выбрать одну конкретную task. Task IDs и выбранные breakpoints относятся к текущему play.

Создайте один или несколько breakpoints, затем используйте `g` или `go`:

```text
break task 'Exercise a loop'
break role application
break tag deployment
break list
go
```

`break task` применяет Python regular expression к полному имени task и использует поиск подстроки. Это regexp, а не glob: символ `*` повторяет предыдущий элемент regexp и не может находиться в начале выражения. Поэтому `*application*` некорректен и приводит к ошибке `nothing to repeat`. Для поиска слова в любой части имени достаточно самого слова:

```text
break task application
```

Выражение `.*application.*` тоже работает, но окружающие `.*` избыточны, поскольку поиск и так выполняется по всему имени через regexp `search`.

Примеры regexp для имени task:

| Задача | Команда |
|---|---|
| Имя содержит `application` | `break task application` |
| Поиск без учёта регистра | `break task '(?i)application'` |
| Имя начинается с префикса role | `break task '^test_role : Render'` |
| Имя заканчивается словом `configuration` | `break task 'configuration$'` |
| Одна из двух tasks | `break task 'Exercise (a loop\|a condition)'` |
| Произвольный текст между словами | `break task 'Render.*configuration'` |
| Буквальная точка | `break task 'version 1\.2'` |
| Буквальный символ `*` | `break task 'file \* generated'` |

Полное имя role-task обычно выглядит как `test_role : Exercise a loop`, поэтому anchors `^` и `$` должны учитывать префикс role. Выполните `w`, чтобы увидеть текущее имя и исходное определение task.

Всё значение breakpoint можно заключить в одинарные или двойные кавычки: они используются только для группировки и не становятся частью выражения. Кавычки необязательны, поскольку остаток строки считается одним значением, поэтому `break task Exercise a loop` и `break task 'Exercise a loop'` эквивалентны. Breakpoints по role и tag используют точное, регистрозависимое совпадение, а не regexp, и поддерживают такие же кавычки. Каждый breakpoint получает числовой ID и удаляется командой `break delete ID`.

`go` выполняет текущую task и подавляет обычные prompts до совпадения с любым breakpoint. В момент вывода `BREAKPOINT HIT` и обычного prompt совпавшая task ещё не выполнена. Без созданных breakpoints команда `go` отклоняется. Используйте `c`, если последующая интерактивная остановка не нужна. Во время `go` проверка ошибок остаётся активной.

### Поведение в check mode Ansible

Inspector можно использовать одновременно с check mode и diff mode Ansible:

```bash
ansible-playbook -i inventory playbook.yml \
  --limit 'web01,web02' --check --diff --step
```

`inspect_step` не реализует собственный механизм симуляции. Он сохраняет check-mode context Ansible и передаёт подтверждённые tasks штатному executor. Заголовок task, preview исходного определения, prompt, выбор host, watches и breakpoints ведут себя так же, как при обычном step-запуске. Проверить эффективный режим можно из любого prompt:

```text
v ansible_check_mode
eval {{ ansible_check_mode }}
```

При запуске с `--check` обе команды должны вывести `True`.

Команды выполнения имеют следующий смысл:

| Команда | Поведение с `--check` |
|---|---|
| `r`, `run` | Поставить текущую task в очередь с `ansible_check_mode=True`; поддерживающий режим модуль прогнозирует результат |
| `r!`, `run!` | Аналогично `run`, но task-level `no_log` отключён для выбранного check-mode result |
| `s`, `skip` | Вообще не ставить task в очередь; эта task не создаёт прогноз или registered result |
| `c`, `continue` | Поставить текущую и последующие tasks в очередь в check mode и отключить дальнейшие обычные prompts |
| `g`, `go` | Ставить tasks в очередь в check mode до совпадения breakpoint; совпавшая task всё ещё остановлена до выполнения |
| `result`, `result!` | Показать предыдущий фактический check-mode result; `changed` обычно означает «изменилась бы» |

Продолжают действовать штатные правила check mode Ansible:

- модули с поддержкой check mode проверяют текущее состояние и прогнозируют `ok`, `changed`, `skipped` или ошибку, не применяя изменение на managed host;
- неподдерживающие режим модули могут быть пропущены или вернуть неполные данные, поэтому registered variables и последующие conditions могут отличаться от обычного запуска;
- facts всё ещё могут быть собраны, а `set_fact` может обновить variables внутри текущего процесса controller, чтобы их использовали последующие симулируемые tasks;
- `changed_when` и `failed_when` вычисляются по check-mode result, когда в нём достаточно данных;
- task с прогнозом `changed` может уведомить handler; handler также обрабатывается в check mode, если его task не переопределяет режим;
- ошибки syntax, undefined variables, validation аргументов, connectivity, privileges, templates и явного `fail` всё ещё могут завершить task с ошибкой;
- `--diff` добавляет прогноз before/after для таких модулей, как `template` и `copy`, если они его поддерживают.

Команды inspector выполняются на controller и не становятся автоматически нейтральными из-за `--check`:

- `w`, `hosts`, `v`, `vars`, `raw`, `result`, управление breakpoints и watches только читают или изменяют состояние debugger;
- `eval`, `eval-all`, `loop eval` и watches продолжают блокировать lookup plugins Ansible;
- `set` действительно меняет непостоянные in-memory variables inspector для текущего запуска, хотя не записывает inventory или variable files;
- `eval-lookup` выполняет настоящий lookup, включая обращения к Vault, командам, файлам, DNS или сети, и может иметь внешние side effects;
- `args`, `when`, `loop`, `template`, `loop when`, `loop args` и `loop template` используют штатный templating Ansible и могут выполнить lookups, встроенные в task или template;
- `template` не записывает remote destination, но читает и рендерит template-данные на controller;
- `template-save` действительно создаёт защищённый локальный файл на controller даже с `--check` и никогда не перезаписывает существующий файл.

Поэтому check mode Ansible является средством прогноза, а не транзакцией или границей безопасности. Task с `check_mode: false` явно принудительно выполняется в обычном режиме, даже если playbook запущен с `--check`. Action plugins, lookup plugins, callbacks, fact caches, logging, custom modules и внешние сервисы также могут иметь реальные controller-side или внешние эффекты. Модуль может поддерживать check mode неполно, а изменяемые внешние данные могут различаться между preview и последующим обычным запуском.

Обычный workflow `inspect-failure>` остаётся активным для ошибок, полученных в check mode. Игнорирование такой ошибки меняет только controller-side состояние Ansible и recap текущего запуска. Оно не делает task безопасной и не может отменить реальный эффект `check_mode: false`, lookup, plugin или создания локального файла на controller.

### Продолжение после ошибки task

Если task, запущенная через `r`, `run`, `r!`, `run!`, `c` или `continue`, завершается ошибкой, которая ещё не обработана через `ignore_errors` или `block`/`rescue`, plugin выводит:

```text
INSPECT FAILURE: application : Configure service
Failed host: web01
The decision applies to failures from this task on 2 active hosts.

inspect-failure>
```

Выберите одно из действий:

- `i` или `ignore` — преобразовать ошибки этой task в ignored-результаты и продолжить. Текущая настройка обычного step mode сохраняется.
- `c` или `continue` — преобразовать ошибки в ignored-результаты, продолжить playbook и отключить последующие обычные остановки `inspect-step>`.
- `a` или `abort` — сохранить штатное failed-состояние Ansible. Failed hosts исключаются из последующих обычных task.

Решение принимается один раз и применяется ко всем активным hosts, на которых завершилась ошибкой та же task. Host, успешно выполнивший task, не изменяется. После игнорирования ошибки recap показывает `failed=0` и увеличивает `ignored` для восстановленных hosts. Исходное сообщение `fatal` остаётся в выводе, поскольку решение принимается после получения результата task.

Failure prompt остаётся доступным во время запуска, начатого с `--step`, даже если обычные prompts task ранее были отключены через `c`. Это позволяет обработать ошибку после автоматического участка play.

Функция не перехватывает unreachable-результаты. Она также не заменяет существующую обработку ошибок Ansible: `ignore_errors` продолжает выполнение автоматически, а `block`/`rescue` переходит в rescue-ветку без дополнительного failure prompt.

## 9. Повторный вывод task и список hosts

После длинного вывода переменных используйте `w`, чтобы снова увидеть текущую task:

```text
inspect-step> w
```

Команда `hosts` показывает hosts, выбранные для текущего play после обработки inventory и `--limit`:

```text
inspect-step> hosts
HOSTS IN CURRENT PLAY (--limit applied)
  web01 (default inspection host, active for current task)
  web02 (active for current task)
```

Host может принадлежать play, но не быть активным для текущей task. Метки явно показывают это различие.

## 10. Единая команда `vars` и alias `v`/`var`

`vars` — основная команда просмотра переменных. `v` и `var` — её короткие alias: все три команды используют один parser, одинаковые параметры и правила маскирования. Для вывода без маскирования доступны `vars!`, `v!` и `var!`.

### Все переменные task

```text
inspect-step> vars
VARIABLES [web01]
{...}
```

Значения поступают из Ansible `VariableManager` для текущих play, host и task. Поэтому учитываются штатные источники и precedence Ansible: role defaults и vars, inventory и group/host vars, play/task vars, facts, зарегистрированные результаты, `set_fact`, extra vars и magic variables.

Короткий alias даёт тот же результат:

```text
v
v depth=1
```

### Точное имя и вложенный path

```text
vars app_port
v app_config.workers
vars json_settings.limits.connections
v application_servers.0.address
```

Dot notation проходит по mappings и декодированным JSON objects. Числовые компоненты path индексируют lists и tuples. Если строка содержит корректный JSON object или array, она декодируется перед проходом по path и форматированным выводом. Для ключей с символами вне имени переменной используйте квадратные скобки Jinja, например `v app_config['foo-bar']`.

Метка host выводится всегда. По умолчанию используется inspection host из заголовка task. Другой host выбирается только явным параметром `host=NAME`:

```text
vars app_port host=web02
v app_port host=web02 depth=1
```

Позиционный синтаксис `vars app_port web02` не поддерживается: он неоднозначен, если имя host совпадает с именем переменной.

### Выражения Jinja

После имени команды можно ввести выражение с фильтрами, функциями Ansible и несколькими переменными без `{{ }}`:

```text
var app_password | length
vars app_config.workers + 2
v [app_root, app_config.workers] | to_json
set tg test
v groups[tg]              # список серверов группы test
v groups[tg][0]           # первый сервер: test01
```

Выражение вычисляется в контексте выбранного host; параметры `host=HOST` и `depth=N` доступны как обычно. Lookup plugins отключены. Результат типа mapping маскируется по ключам, но вычисленное скалярное значение может раскрыть секрет. Не выводите секреты через выражения в журнал.

### Glob и regexp

Glob — простой шаблон для поиска имён переменных. Перед шаблоном обязателен префикс `glob=`, чтобы команда выполняла поиск имён. Сравнивается полное имя переменной верхнего уровня:

```text
v glob=role_*       # role_name, role_port: * — ноль или больше символов
v glob=*port*       # app_port, role_port: port в любом месте имени
v glob=role_?       # role_a, но не role_ab: ? — ровно один символ
v glob=role_[ab]    # role_a и role_b: [ab] — один из указанных символов
```

Без `glob=` квадратные скобки означают индексацию Jinja. Например, `v groups[tg][0]` получает первый host группы, имя которой хранится в `tg`. Операторы тоже вычисляются как выражения: `v a*b` перемножает две переменные. Старую команду `v role_*` нужно заменить на `v glob=role_*`.

Для регулярных выражений Python используется отдельный префикс `regex=`. Выражение должно совпасть с полным именем переменной верхнего уровня:

```text
vars regex=^application_.*$
v regex=^(role|application)_[a-z0-9_]+$
```

Поиск по glob и regexp показывает все совпавшие значения вместе; вложенные ключи он не просматривает.

### Неопределённые значения и неверный regexp

Ошибка просмотра не завершает playbook и возвращает текущий prompt:

```text
Variable 'missing_name' is undefined
Variable path 'app_config.missing_key' is undefined
Invalid variable regexp: nothing to repeat at position 0
```

## 11. Глубина, `hostvars` и маскирование

### Ограничение глубины вывода

После сбора facts полный вывод может быть очень большим. Положительный параметр `depth=N` сворачивает вложенные контейнеры и работает одинаково для `vars`, `v` и `var`:

```text
vars depth=1
v depth=2 host=web02
vars ansible_facts depth=1
v ansible_facts.python depth=2 host=web02
```

Глубина отсчитывается от выбранного корня:

- `vars depth=1` показывает первый уровень полного mapping переменных;
- `vars app_config depth=1` показывает первый уровень внутри `app_config`;
- `v app_config.limits depth=1` показывает первый уровень внутри `limits`.

Свёрнутые значения обозначаются так:

```text
<mapping: 93 keys>
<list: 4 items>
<tuple: 2 items>
```

Selector, `host=HOST` и `depth=N` можно указывать в любом порядке, каждый не более одного раза. `depth` должен быть положительным целым числом. Без `depth` выбранное значение выводится полностью.

### `hostvars`

Без `host=HOST` команда сохраняет стандартное поведение Ansible и выводит mapping всех hosts, доступных через `hostvars`:

```text
vars hostvars
```

Явный host выбирает соответствующую запись `hostvars`:

```text
v hostvars host=web02
vars hostvars.ansible_facts host=web02
```

Имя host также можно включить непосредственно в path:

```text
vars hostvars.web02.ansible_facts.python.version
```

### Маскирование секретов

`vars`, `v` и `var` по умолчанию рекурсивно заменяют значения, ключи которых содержат распространённые признаки секрета: `password`, `passwd`, `secret`, `token`, `api_key`, `apikey` или `private_key`:

```text
'database_password': '*** HIDDEN ***'
```

Отключение маскирования всегда должно быть явным. `vars!`, `v!` и `var!` также являются полными alias:

```text
vars! app_config host=web02 depth=2
v! app_config host=web02 depth=2
```

## 12. Просмотр выражений, loops, аргументов task и templates

### Исходные аргументы

`raw` выводит `task.args` до подстановки Jinja и Ansible variables:

```text
inspect-step> raw
{'msg': 'service port is {{ app_port }}'}
```

Эта команда не маскирует секреты.

### Аргументы после templating

`args` или её короткий alias `a` выполняет templating аргументов с переменными default inspection host:

```text
inspect-step> args
{'msg': 'service port is 8080'}
```

Распространённые ключи секретов рекурсивно маскируются. Используйте `args!`, чтобы явно отключить маскирование.

Alias `a` доступен в обычном prompt `inspect-step>`. В prompt `inspect-failure>` команда `a` сохраняет отдельное значение: abort с сохранением ошибки Ansible.

Просмотр аргументов является диагностическим. Он использует штатный templating Ansible, поэтому встроенный в аргументы task lookup может выполниться на controller во время preview и повторно при запуске task. Авторитетные templating и validation выполняются Ansible task executor.

### Вычисление составного выражения

Используйте `eval` или короткий alias `e` в любом обычном prompt `inspect-step>`. Весь текст после имени команды считается Jinja template string:

```text
inspect-step> eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
EVAL [web01] =
/tmp/application-web01.conf
```

По умолчанию используется inspection host из заголовка task. Чтобы применить переменные другого host текущего play, добавьте `host=HOST` последним аргументом:

```text
inspect-step> e {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf host=web02
EVAL [web02] =
/tmp/application-web02.conf
```

Поддерживаются Jinja filters, tests, conditions, mappings и sequences. Mapping, sequence или JSON-результат форматируется для чтения:

```text
eval {{ app_config }} host=web02
eval {{ app_port | int + 100 }} host=web02
eval {{ 'enabled' if feature_enabled else 'disabled' }}
```

Undefined variables приводят к warning и возврату в тот же prompt. Lookup plugins Ansible намеренно отключены, поэтому выражения наподобие `{{ lookup('file', '/path') }}` отклоняются и не могут читать файлы, запускать команды или обращаться к внешним системам с controller.

Результат не маскируется, поскольку `eval` является явным запросом эффективного значения. Поэтому команда может раскрыть чувствительные данные, в том числе используемые task с `no_log`.

### Явное вычисление lookup-выражения

Используйте `eval-lookup`, когда выражение должно вызвать lookup plugin Ansible. Без `host=HOST` команда использует inspection host из заголовка task. Завершающий параметр `host=HOST` выбирает один другой host текущего play:

```text
eval-lookup {{ lookup('env', 'HOME') }}
eval-lookup {{ query('fileglob', '/etc/*.conf') }} host=web02
```

Например, если lookup plugin `hashi_vault` установлен, а его параметры подключения и аутентификации доступны Ansible, host-specific выражение Vault можно проверить так:

```text
eval-lookup {{ lookup('hashi_vault', hashicorp_vault_hashi_vault_path_root + (hashicorp_vault_cacertfile | basename)) }} host=test01
```

Команда один раз вычисляет выражение ровно для одного выбранного host и никогда не раскрывает его в `all`. Она недоступна через `eval-all`, и её нельзя добавить в watches. Mapping, sequence или JSON-строка выводятся в форматированном виде. Undefined variable, отсутствующий lookup plugin, ошибка аутентификации или ошибка plugin показываются на экране, после чего inspector остаётся в том же prompt.

Перед каждым вычислением inspector выводит явный warning. Lookup plugins работают на controller, а не на выбранном managed host, и могут читать файлы controller, запускать команды, обращаться к сети или внешним системам либо иметь side effects. Последующий запуск task может повторно выполнить тот же lookup и получить другой результат. Вывод не маскируется, включая данные из Vault и значения, защищённые `no_log` task.

### Сравнение выражения между hosts

`eval-all` вычисляет одно выражение для каждого host, активного на текущей task:

```text
inspect-step> eval-all {{ app_port }}
EVAL [web01] =
8081
EVAL [web02] =
8082
```

Добавьте `diff=true` последним параметром, чтобы свернуть одинаковые успешные значения:

```text
eval-all {{ app_config }} diff=true
```

Если все значения равны, inspector выводит `no differences` и одно значение. Иначе выводится значение каждого host. Ошибка вычисления показывается отдельно для host и не закрывает текущий prompt. Lookups отключены, результаты не маскируются.

### Предварительная проверка `when`

Используйте тот же conditional evaluator Ansible, который решит, должна ли выполняться текущая task:

```text
when
when web02
when all
```

По умолчанию используется inspection host; `all` выбирает все hosts, активные на текущей task. Каждое condition показывается как `TRUE`, `FALSE` или `ERROR`, после чего выводится итоговое решение `RUN`, `SKIP` или `ERROR`. Conditions после первого false помечаются `NOT EVALUATED`, что сохраняет short-circuit поведение Ansible. Для task без conditions выводится `RUN (no conditions)`.

В отличие от `eval`, эта команда намеренно следует штатной семантике conditions Ansible. Lookup, явно присутствующий в `when` task, может выполниться на controller во время preview, а затем ещё раз при вычислении task executor.

### Preview элементов loop

На task с `loop` или legacy `with_*` можно раскрыть элементы без выполнения task:

```text
loop
loop test02
loop all
loop all depth=1
loop! test02 depth=2
```

По умолчанию используется inspection host. Явный host выбирает этот host play, а `all` выводит отдельный preview для каждого host, активного на текущей task. Поэтому host-specific variables могут давать разное количество и разные значения элементов. `depth=N` отсчитывается от корня каждого item.

Preview показывает:

- источник `loop` или legacy lookup `with_*`;
- количество раскрытых элементов;
- эффективный `loop_var`;
- zero-based `index_var`, если он настроен;
- включение extended loop metadata;
- отрендеренный `loop_control.label`, если он настроен;
- каждый раскрытый item в порядке выполнения.

Пример:

```text
LOOP PREVIEW [test02]: 3 items
  source: loop
  loop_var: item
  index_var: loop_index (zero-based)
  extended: true
  ITEM 1/3
  loop_index = 0
  label =
'alpha'
  item =
'alpha'
```

`loop` рекурсивно маскирует распространённые имена ключей секретов в структурированных items. `loop!` явно отключает маскирование. Маскирование остаётся эвристическим: scalar-секреты или custom labels с другими именами всё равно могут быть показаны.

Команда использует те же механизмы templating и lookup поддерживаемых версий Ansible, что и выполнение task. Поэтому lookup внутри `loop`, `query` или legacy `with_*` может прочитать файл, запустить команду или обратиться к внешней системе на controller во время preview, а затем выполниться ещё раз при реальном запуске task. Перед вычислением inspector показывает warning. Результат lookup также может измениться между preview и выполнением.

Сам `loop` preview не выполняет item, не подставляет его в аргументы task, не заполняет `register`, не вызывает handlers и не изменяет recap. Обычный prompt по-прежнему открывается один раз для всей task, а не для каждого item.

### Вычисление в контексте выбранного item loop

После `loop` preview выберите item по его 1-based номеру `ITEM N/M` и выполните одну диагностическую операцию:

```text
loop eval 2 {{ item }}:{{ template_index }}:{{ ansible_loop.last }} host=test01
loop when 2 host=test01
loop args 2 host=test01
loop template 2 host=test01
```

Без `host=HOST` используется default inspection host. Режима `all` нет: одна команда формирует контекст одного item для одного host. Контекст содержит эффективный `loop_var`, настроенный zero-based `index_var`, `ansible_loop_var` и extended metadata `ansible_loop`, когда `loop_control.extended` включён.

- `loop eval` вычисляет Jinja-expression с отключёнными Ansible lookups; результат не маскируется;
- `loop when` применяет настоящие conditions текущей task и показывает итог `RUN` или `SKIP`;
- `loop args` выполняет templating `task.args` и маскирует распространённые ключи секретов;
- `loop template` работает на looped task `ansible.builtin.template` и показывает немаскированное rendered content.

Каждая команда заново раскрывает loop. Поэтому lookup в `loop`/legacy `with_*`, conditions, аргументах или template может выполниться на controller и затем повториться при реальном запуске task. Inspector предупреждает об этом риске, а результат диагностики может отличаться от последующего выполнения.

Item при этом не выполняется: не создаются partial results, `register`, notifications handlers или изменения recap. Для реального выполнения всей loop-task по-прежнему используется `r`; per-item run/skip не поддерживаются.

#### Полная демонстрационная последовательность

Встроенный пример содержит loop-task `test_role : Render loop-aware application configuration` с двумя items: `primary` и `disabled`. Запустите playbook для обоих тестовых hosts:

```bash
cd example
ansible-playbook -i inventory playbook.yml \
  --limit 'test01,test02' \
  --step
```

На первой остановке установите breakpoint и перейдите к демонстрационной task:

```text
inspect-step> break task '^test_role : Render loop-aware application configuration$'
BREAKPOINT #1 added

inspect-step> g
GO: running until a breakpoint matches
```

После срабатывания breakpoint сначала раскройте loop для обоих hosts:

```text
inspect-step> loop all
```

Для каждого host будут показаны два элемента и zero-based `template_index`:

```text
ITEM 1/2
  template_index = 0
  item = 'primary'

ITEM 2/2
  template_index = 1
  item = 'disabled'
```

Вычислите expression в контексте первого item для `test02`:

```text
inspect-step> loop eval 1 {{ inventory_hostname }}:{{ item }}:{{ template_index }}:{{ ansible_loop.first }} host=test02
```

Ожидаемый результат:

```text
LOOP ITEM CONTEXT [test02] ITEM 1/2
  item =
'primary'
EVAL [test02] =
test02:primary:0:True
```

Составной path вычисляется в том же контексте:

```text
inspect-step> loop eval 1 {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}-{{ item }}.conf host=test02
EVAL [test02] =
/tmp/inspect-test-test02-primary.conf
```

Проверьте `when` для первого item:

```text
inspect-step> loop when 1 host=test02
  1. TRUE: item != "disabled"
WHEN [test02]: RUN
```

Просмотрите templated-аргументы task:

```text
inspect-step> loop args 1 host=test02
{'dest': '/tmp/inspect-test-test02-primary.conf', 'mode': '0640', 'src': 'loop-application.conf.j2'}
```

Отрендерите template без выполнения item и записи remote destination:

```text
inspect-step> loop template 1 host=test02
TEMPLATE PREVIEW [test02]
Destination: /tmp/inspect-test-test02-primary.conf
----- BEGIN TEMPLATE -----
# Generated for inspect_step loop item preview
host=test02
profile=primary
profile_index=0
first=True
destination=/tmp/inspect-test-test02-primary.conf
----- END TEMPLATE -----
```

Второй item демонстрирует контекст, в котором condition запрещает выполнение:

```text
inspect-step> loop eval 2 {{ item }}:{{ template_index }}:{{ ansible_loop.last }} host=test02
EVAL [test02] =
disabled:1:True

inspect-step> loop when 2 host=test02
  1. FALSE: item != "disabled"
WHEN [test02]: SKIP
```

Даже при решении `SKIP` команды `loop args 2 host=test02` и `loop template 2 host=test02` позволяют диагностически проверить результат templating. Они не обходят condition и не выполняют item.

Чтобы завершить демонстрацию без выполнения loop-task, используйте:

```text
inspect-step> s
inspect-step> c
```

Чтобы штатно выполнить loop-task целиком, используйте `r`: item `primary` выполнится, а `disabled` будет пропущен по `when`.

### Просмотр результата предыдущей task

В prompt следующей task можно посмотреть последний обработанный результат:

```text
result
result web02 depth=2
result all depth=1
result! all
```

Вывод содержит имя предыдущей task, host и вычисленный status: `ok`, `changed`, `skipped`, `failed`, `unreachable` или `ignored`. По умолчанию выбирается текущий inspection host. `all` показывает все hosts, для которых сохранён результат предыдущей task. `depth=N` ограничивает контейнеры относительно выбранного корня по тем же правилам, что и `vars`.

`result` рекурсивно маскирует распространённые имена ключей секретов и исключает служебные transport-поля Ansible `_ansible_*`. `result!` явно отключает маскирование. До завершения первой task команда сообщает, что предыдущего результата ещё нет.

### Наблюдение за выражениями

Watches автоматически вычисляются сразу после вывода task source на каждой интерактивной остановке:

```text
watch add {{ app_port }}
watch add {{ hostvars[inventory_hostname].host_color }} host=web02
watch list
watch delete 1
```

Без `host=HOST` watch следует за default inspection host каждой остановки. С host он закрепляется за указанным активным host play. Watches получают локальные для процесса числовые IDs и исчезают после завершения `ansible-playbook`. Lookup plugins отключены, но значения watches не маскируются и могут раскрыть секреты. Для tasks, пропущенных командой `go`, watches не вычисляются, поскольку интерактивной остановки нет.

### Preview результата `ansible.builtin.template`

На task, использующей `ansible.builtin.template`, отрендерите источник для default inspection host без выполнения task:

```text
inspect-step> template
TEMPLATE PREVIEW [web01]
Source: /project/roles/application/templates/app.conf.j2
Destination: /etc/application/app.conf
----- BEGIN TEMPLATE -----
listen_port=8080
node=web01
----- END TEMPLATE -----
```

При нескольких активных hosts укажите host, для которого нужно применить его собственные переменные:

```text
template web02
```

Сохраните точные отрендеренные байты в локальный файл на Ansible controller:

```text
template-save previews/web02-app.conf web02
template-save "/tmp/preview files/web02-app.conf" web02
```

Относительный `LOCAL_PATH` разрешается от каталога, из которого был запущен `ansible-playbook`. Родительский каталог должен уже существовать. Для защиты от случайной потери данных существующий файл никогда не перезаписывается. Новый файл создаётся с mode `0600`; настройка task `output_encoding` учитывается.

При рендеринге используются action/module defaults task, настройки `src`, `dest`, Jinja-разделителей, whitespace, newline, search path для include и metadata template. Рендеринг следует штатному templating Ansible, поэтому lookups в аргументах или содержимом template могут выполниться на controller во время preview и повторно при запуске task. Preview зависит от host и не записывает удалённый `dest`; запускайте task через `r` только после проверки результата.

Полное отрендеренное содержимое намеренно не маскируется, поскольку маскирование сделало бы preview неточным. Перед выводом или сохранением показывается warning. Поэтому значения могут быть раскрыты даже для task с `no_log`.

## 13. Изменение переменных во время выполнения

`set` создаёт или заменяет top-level переменную через Ansible cache непостоянных facts.

### Изменение переменной для всех hosts play

По умолчанию область действия включает каждый host текущего play после `--limit`:

```text
set app_port 9000
set feature_enabled true
set deployment_mode blue
set app_config '{"workers": 4, "limits": {"connections": 200}}'
```

Ответ перечисляет затронутые hosts, но не повторяет значение:

```text
SET app_port for hosts: web01, web02
```

### Изменение переменной для одного host

Используйте явный параметр `host=HOST`:

```text
set app_port 9002 host=web02
```

Host должен быть активным в текущем play.

### Типы значений и кавычки

Значение разбирается безопасным YAML loader, поэтому числа, booleans, null, mappings и sequences сохраняют тип. JSON является допустимым YAML и удобен для структурированных значений.

Вся команда вводится в одной строке и использует shell-подобные правила кавычек. Чтобы принудительно сохранить строку, похожую на YAML boolean или число, оставьте YAML-кавычки внутри команды:

```text
set feature_mode '"true"'
set release_code '"0012"'
```

Имя переменной должно соответствовать `[A-Za-z_][A-Za-z0-9_]*`. Вложенное присваивание вида `set app_config.workers 8` не поддерживается: необходимо заменить всю top-level структуру.

### Время жизни и precedence

Новое значение доступно команде `vars` (и её alias `v` и `var`), команде `args`, текущей ожидающей task и последующим task. Оно не записывается в inventory, variable files или playbook и исчезает после завершения процесса `ansible-playbook`.

Последующий `set_fact` или зарегистрированный результат может заменить значение. Extra vars, переданные через `-e`, и magic variables Ansible имеют более высокий приоритет и не могут быть переопределены этой командой.

## 14. История команд и редактирование строки

Если доступен Python `readline`, а стандартный ввод подключён к интерактивному терминалу:

- ↑ и ↓ перемещаются по истории команд;
- ← и → перемещают курсор;
- Backspace/Delete редактируют текущую команду;
- возвращённую из истории команду можно изменить и снова выполнить.

История существует только в текущем процессе `ansible-playbook` и не сохраняется между запусками. При перенаправленном вводе или pipeline команды по-прежнему читаются, но терминальное редактирование строки недоступно. Если стрелки выводят последовательности вида `^[[A`, prompt не использует readline или модуль недоступен.

## 15. Рекомендуемый процесс отладки

1. Начните с одного host: `--limit web01 --step`.
2. Прочитайте автоматический preview task до ввода команды выполнения.
3. После сбора facts используйте `vars depth=1` для общего обзора.
4. Сузьте исследование через `vars NAME`, `v PATH depth=N`, `glob=PATTERN` или явный `regex=REGEXP`.
5. Используйте `when all` и `eval-all JINJA diff=true`, чтобы сравнить решения и значения между hosts.
6. На task с loop используйте `loop all depth=N`, чтобы сравнить раскрытые items до выполнения.
7. Используйте `args` для проверки templated-аргументов и `result all depth=2` для просмотра предыдущей task.
8. Добавьте watches для значений, которые нужно отслеживать на нескольких остановках.
9. На task `ansible.builtin.template` используйте `template [HOST]` или `template-save FILE [HOST]` для проверки результирующего файла.
10. При необходимости выполните `set` и сразу проверьте эффективное значение через `v`, `eval`, `args`, `loop` или `template`.
11. После длинного вывода используйте `w`, чтобы восстановить контекст task.
12. Для длинного прохода создайте узкие breakpoints и используйте `go`; иначе выберите `r`, `s` или `c`. Используйте `r!` только когда раскрытие результата выбранной task явно необходимо.
13. При появлении `inspect-failure>` изучите fatal-результат и явно выберите `ignore`, `continue` или `abort`.

При нескольких hosts сначала выполните `hosts` и явно указывайте host в командах просмотра, когда значения зависят от host.

Если поддержка модулей известна, начните с `--check --diff --step`, воспринимайте `changed` как прогноз и проверяйте его через `result`. Повторяйте запуск без `--check` только после проверки lookups, переопределений `check_mode`, controller-side записей и спрогнозированных diffs.

## 16. Безопасность

Маскирование является эвристикой, а не границей безопасности. Оно распознаёт имена ключей, содержащие небольшой список распространённых терминов. Чувствительные значения под ключами с другими именами всё равно могут быть выведены.

Команды, по умолчанию маскирующие распространённые имена ключей секретов:

- автоматический preview исходного определения task;
- `w`;
- `vars`, `v` и `var`;
- `loop`;
- `result`;
- `args`;
- выбранный item, выводимый перед `loop eval`, `loop when`, `loop args` или `loop template`;
- `loop args`.

Команды, способные выводить значения без маскирования:

- `r!` и `run!`;
- `e` и `eval`;
- `eval-lookup`;
- `eval-all` и watches;
- `raw`;
- `vars!`, `v!` и `var!`;
- `loop!`;
- `result!`;
- `args!`;
- `template` и `template-save`;
- `loop eval` и `loop template`.

`set` не повторяет значение в ответе, но исходная команда остаётся на экране терминала и в readline history текущего процесса. Не вводите production-секреты, если вывод терминала или запись сессии не являются доверенными.

Ansible `no_log` не превращает inspector в полноценный фильтр секретов. `r!` намеренно отключает task-level `no_log` для одной выбранной task и может раскрыть её result через все включённые callbacks. Module-level маскирование аргументов и controller-wide `DEFAULT_NO_LOG` независимы и могут продолжить скрывать вывод. Внимательно проверяйте preview task и используемые диагностические команды.

`eval`, `eval-all`, `loop eval` и watches отключают lookup plugins Ansible, чтобы предотвратить их controller-side side effects. Jinja filters и tests, включая добавленные проектом расширения, продолжают выполняться, поэтому используйте только доверенные выражения. `eval-lookup` является явным исключением: команда включает lookup plugins для одного вызова и одного host, каждый раз показывает warning и не маскирует результат. Preview `when` и loop, просмотр templated-аргументов, preview template, `loop when`, `loop args` и `loop template` используют штатное вычисление Ansible, поэтому встроенный lookup может выполниться на controller во время preview.

`--check` не усиливает эти свойства безопасности. Он только просит поддерживающие его модули спрогнозировать изменения managed host. Режим не подавляет controller-side lookups, локальные preview-файлы, поведение plugins или callbacks, caches, logging и task с явным `check_mode: false`.

Игнорирование ошибки не отменяет изменения, которые failed-модуль уже мог выполнить на управляемом host. Используйте recovery-действие только после оценки безопасности дальнейшего выполнения.

## 17. Диагностика проблем

### Plugin не найден

Проверьте `strategy_plugins` в `ansible.cfg`, текущий рабочий каталог и наличие в play:

```yaml
strategy: inspect_step
```

### Версия выводится, но prompt отсутствует

Добавьте `--step` в команду `ansible-playbook`. Без step mode плагин намеренно ведёт себя как `linear`.

### Task пропущена или всё-таки имеет эффект с `--check`

Сначала проверьте `v ansible_check_mode`. Пропущенная task может использовать модуль без поддержки check mode; просмотрите её `result` и не считайте registered data эквивалентными обычному запуску. Вывод `changed` является прогнозом, а не доказательством remote-изменения. Если возник реальный эффект, проверьте `check_mode: false`, controller-side lookups, `eval-lookup`, `template-save`, action или callback plugins, fact caches, logging и поведение custom module. Используйте `--diff`, где он поддерживается, и повторите проверку на одноразовой тестовой цели, если нужен авторитетный результат.

### Playbook завершается после ошибочной task

Если запуск был начат с `--step`, используйте `i` в prompt `inspect-failure>`, чтобы проигнорировать ошибки этой task и продолжить отладку, или `c`, чтобы продолжить без обычных остановок task. Команда `a` сохраняет failed-состояние Ansible. Без `--step` plugin не изменяет штатную обработку ошибок Ansible.

### `Original task definition is unavailable`

Это ожидаемо для синтетических task Ansible, например неявного сбора facts. Просмотр переменных и выполнение task остаются доступными.

### Стрелки печатают escape-последовательности

Используйте интерактивный терминал и проверьте, что Python может импортировать `readline`. При перенаправленном или переданном через pipe stdin редактирование строки недоступно.

### Вывод `vars` слишком большой

Начните с `vars depth=1`, затем исследуйте ветвь через `vars PATH depth=N` или отдельное значение через `v PATH`.

### Переменная или path не определены

Выполните `vars depth=1` или используйте шаблон, например `v glob=prefix_*` либо `vars regex=^prefix_.*$`, чтобы проверить top-level имя. Шаблоны ищут только top-level имена переменных.

### `eval` не может вычислить выражение

Проверьте, что каждая используемая переменная существует для host, указанного в `EVAL [HOST]`. Другой host выбирается завершающим параметром `host=HOST`. Warning о lookup ожидаем, поскольку lookup plugins для этой команды намеренно отключены.

### `eval-lookup` не может вычислить выражение

Сначала проверьте host-specific variables через `vars PATH host=HOST`, затем убедитесь, что Ansible находит lookup plugin и что на controller доступны его dependencies, configuration, credentials, файлы и сеть. Для Vault lookup ошибка аутентификации или сертификата приходит от lookup plugin; inspector показывает её и остаётся в том же prompt. Указывайте `host=HOST` только последним параметром `eval-lookup` и помните, что lookup работает на controller, хотя variables берутся из контекста выбранного host.

### `go` не запускается или останавливается слишком часто

Для `go` нужен хотя бы один breakpoint. Выполните `break list` и учитывайте, что breakpoint по task является regular expression, а role и tag используют точное совпадение. Слишком широкое правило удаляется через `break delete ID`.

### Preview loop сообщает ошибку или другие items

Убедитесь, что текущая task содержит `loop` или `with_*`, выбранный host имеет все используемые variables, а раскрытое значение современного `loop` является list. Lookup может вернуть другие данные при повторном вычислении во время реального выполнения. Используйте `loop all` для поиска host-specific различий и `depth=N` для ограничения больших структур items.

### `set` сообщил об успехе, но эффективное значение не изменилось

Проверьте, не является ли имя extra var (`-e`) или magic variable с более высоким precedence. Также проверьте, не заменяет ли значение последующий `set_fact`, зарегистрированный результат, role parameter или include parameter.

### Структурированное значение `set` отклоняется

Используйте корректный однострочный YAML или JSON и заключите его в кавычки как одно значение командной строки:

```text
set settings '{"enabled": true, "ports": [8080, 8081]}'
```

### `vars` неожиданно выбирает host

Для выбора host нужен параметр `host=HOST`. Bare-имя host остаётся частью selector или выражения; для просмотра его данных используйте path `hostvars.web02`.

### Preview template не удаётся отрендерить

Убедитесь, что текущая task использует `ansible.builtin.template`, `src` существует в обычном Ansible search path для templates, а все используемые переменные определены для выбранного host. Для template-task с loop обычная команда `template` не имеет значения `item`; используйте `loop template ITEM [host=HOST]`.

Если `template-save` сообщает, что локальный файл уже существует, выберите новый path. У команды намеренно нет режима перезаписи.

## 18. Ограничения

- Техническая совместимость ограничена `ansible-core 2.12.x` и 2.13.x; основная протестированная версия — 2.13.13.
- Точность check mode зависит от каждого модуля и plugin: `changed` является прогнозом, неподдерживающие режим модули могут пропускаться, а registered values — отличаться от обычного запуска.
- `--check` не подавляет `check_mode: false`, controller-side эффекты lookup/plugins, in-memory изменения `set` или локальные файлы, созданные `template-save`.
- Inspector останавливается один раз на task, а не на каждом элементе loop.
- Preview и item-aware команды loop не дают per-item выполнения, пропуска, retries или регистрации результатов.
- Lockstep-task создаёт один prompt для своей активной группы hosts.
- Preview `when` является диагностическим; executor повторно вычисляет condition после `run`, поэтому изменяемое состояние или lookups могут дать другое решение.
- Каждая явная meta-task открывает один prompt inspector для своей активной lockstep-группы hosts; неявные lifecycle-tasks meta и noop, созданные Ansible, prompt не открывают.
- `run-all` работает только для dynamic `include_tasks` и `include_role`; static imports раскрываются до запуска strategy и не могут открыть prompt уровня import.
- `r!` отключает task-level `no_log` только для выбранной task; команда не может отменить уже выполненное модулем маскирование или надёжно переопределить controller-wide `DEFAULT_NO_LOG`.
- Вывод исходного определения нормализует YAML и не сохраняет комментарии.
- `set` изменяет только top-level переменные и не сохраняет изменения постоянно.
- Команды просмотра, watches и управление breakpoints доступны в обычных pre-task prompts `inspect-step>`, но не в post-failure prompt выбора дальнейшего действия.
- Lookup plugins отключены для `eval`, `eval-all`, `loop eval` и watches; эти команды всё равно вычисляют variables, Jinja operators, filters, tests, mappings и sequences.
- `eval-lookup` вычисляет одно выражение для одного host play; команда не имеет режимов `all`, watch или автоматического `eval-all`, а её немаскированный результат может отличаться при повторном lookup во время task.
- Preview loop использует штатный templating Ansible и может выполнять controller-side lookup plugins.
- Preview templated-аргументов и template может выполнять controller-side lookups, встроенные в task или template.
- Watches и breakpoints существуют только в текущем процессе `ansible-playbook`.
- Preview template поддерживает встроенные action names `template`, `ansible.builtin.template` и `ansible.legacy.template`; совместимость посторонних collection actions с именем `template` не предполагается.
- Обычная команда `template` не создаёт loop variables; для looped template используйте `loop template ITEM`, который диагностически создаёт контекст выбранного item.
- Сохранённый preview template является локальным файлом controller и никогда не перезаписывает существующий файл.
- Post-failure recovery обрабатывает failed-результаты task, но не unreachable hosts.
- Одно recovery-решение применяется ко всем ошибкам одной lockstep-task.
- Игнорирование ошибки изменяет состояние выполнения на controller и статистику recap, но не отменяет изменения на удалённых hosts.
- Интерактивное редактирование зависит от Python `readline` и терминального stdin.
- Маскирование секретов не может обнаружить каждое чувствительное значение.

## 19. Архитектура и файлы проекта

Основная реализация находится в `strategy_plugins/inspect_step.py`. Класс наследует `ansible.plugins.strategy.linear.StrategyModule` и интегрируется с step hook Ansible 2.12-2.13, lockstep-выбором task, обработкой pending results, выполнением handlers, постановкой task в очередь, `VariableManager` и `Templar`.

Архитектурные диаграммы хранятся как исходные файлы PlantUML в `diagramms/`:

- `architecture-ru.puml` — компоненты и зависимости;
- `task-lifecycle-ru.puml` — последовательность просмотра и выполнения task;
- `variables-ru.puml` — поток просмотра и runtime-изменения переменных.

Файлы без суффикса `-ru` содержат английские версии тех же диаграмм.

## 20. Запускаемый пример

Каталог `example/` содержит local inventory с двумя hosts, play variables, facts, role defaults и vars, вложенные и JSON-значения, `set_fact`, `register`, host-specific template, handler, host-specific items loop с `loop_control`, condition и помеченную `inspect_demo` цель breakpoint.

Запустите его из каталога примера:

```bash
cd example
ansible-playbook -i inventory playbook.yml --limit test --step
```

Полезные команды для первой сессии:

```text
hosts
vars depth=1
v host_app_port host=test01
vars host_app_port host=test02
vars ansible_facts.python depth=1 host=test02
set host_app_port 9000
set host_app_port 9002 host=test02
eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf host=test02
eval-lookup {{ lookup('env', 'HOME') }} host=test02
eval-all {{ host_app_port }} diff=true
when all
loop all depth=2
result all depth=1
watch add {{ app_port }}
break tag inspect_demo
go
args
template test01
template test02
template-save /tmp/test02-application.conf test02
w
r
i
```

## 21. Примеры всех команд и patterns

### Управление выполнением

```text
r
run
r!
run!
s
skip
c
continue
g
go
```

Для `g` или `go` сначала должен быть создан хотя бы один breakpoint. Команды `c` и `continue` не используют breakpoints и отключают дальнейшие обычные prompts.

### Контекст task и hosts

```text
w
hosts
h
help
?
```

### Переменные через `vars`, `v` и `var`

```text
vars app_port
v app_port
v app_config.workers
vars json_settings.limits.connections
v application_servers.0.address
v app_port host=test02
vars hostvars
v hostvars host=test02
vars hostvars.ansible_facts host=test02
vars glob=role_*
v glob=*port*
vars glob=role_?
v regex=^role_.*$
vars regex=^(role|app)_[a-z0-9_]+$
v regex=^backend_[0-9]+$
var app_password | length
var app_config.workers + host_app_port host=test02
```

`vars`, `v` и `var` полностью эквивалентны. Glob и regexp проверяют только top-level имена; используйте префикс `glob=` или `regex=`. Поиск вложенных значений выполняется через dot-path, а не через pattern.

```text
vars
v
vars host=test02
vars depth=1
v depth=2 host=test02
vars app_config
v app_config depth=1
vars ansible_facts.python depth=2 host=test02
vars! app_config host=test02 depth=3
v! app_config host=test02 depth=3
```

Selector или выражение может содержать несколько слов. Параметры `host=HOST` и `depth=N` допускаются в любом порядке, но каждый только один раз.

### Runtime-изменение variables

```text
set app_port 9000
set feature_enabled true
set deployment_mode blue
set app_port 9002 host=test02
set ports '[8080, 8081]'
set settings '{"workers": 4}'
set release_code '"0012"'
```

### Jinja-выражения

```text
eval {{ app_port }}
e {{ app_port | int + 100 }}
eval {{ app_root }}/{{ app_name }}.conf
eval {{ app_config.workers }} host=test02
eval {{ 'on' if feature_enabled else 'off' }}
eval {{ [app_port, host_color] }}
eval-lookup {{ lookup('env', 'HOME') }}
eval-lookup {{ query('fileglob', '/etc/*.conf') }} host=test02
eval-lookup {{ lookup('hashi_vault', hashicorp_vault_hashi_vault_path_root + (hashicorp_vault_cacertfile | basename)) }} host=test01
eval-all {{ inventory_hostname }}
eval-all {{ host_app_port }} diff=true
eval-all {{ app_config }} diff=true
```

`eval-lookup` выполняется только для default или явно выбранного host; формы `all` нет, и команда не используется watches. `eval-all` работает только с hosts, активными для текущей task. `diff=true` сворачивает одинаковые успешные значения в один вывод.

### Conditions и предыдущий результат

```text
when
when test02
when all
result
result test02
result all
result all depth=1
result! test02 depth=3
```

### Preview loop

```text
loop
loop test02
loop all
loop all depth=1
loop depth=2 test02
loop! all depth=3
loop eval 2 {{ item }}:{{ ansible_loop.index }} host=test01
loop when 2 host=test01
loop args 2 host=test01
loop template 2 host=test01
```

Используйте `loop` для вывода с маскированием, а `loop!` — только когда намеренно нужны открытые значения items. Item-aware команды используют 1-based номер из preview и один host. Они не дают пошагового управления выполнением отдельных items.

### Watches

```text
watch add {{ app_port }}
watch add {{ app_port }} host=test02
watch add {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
watch list
watch delete 1
```

Watch без `host=HOST` использует inspection host каждой следующей остановки. Lookups отключены, но результат не маскируется.

### Breakpoints и regexp

```text
break task application
break task 'Exercise a loop'
break task '(?i)configure|restart'
break task '^test_role : Render'
break task 'condition$'
break role test_role
break tag inspect_demo
break list
break delete 1
g
```

Краткое сравнение patterns:

| Команда | Синтаксис | Способ совпадения | Пример |
|---|---|---|---|
| `vars`, `v`, `var` | `glob=` + pattern | полное top-level имя variable | `v glob=*port*` |
| `vars`, `v`, `var` | `regex=` + Python regexp | полное top-level имя через `fullmatch` | `vars regex=^app_.*$` |
| `break task` | Python regexp | поиск через `search` | `break task application` |
| `break role` | точная строка | регистрозависимое равенство | `break role test_role` |
| `break tag` | точная строка | регистрозависимое равенство | `break tag inspect_demo` |

Следовательно, `break task *application*` неверен, `break task .*application.*` допустим, но избыточен, а рекомендуемый вариант — `break task application`.

### Аргументы task и templates

```text
raw
a
args
args!
template
template test02
template-save /tmp/app.conf test02
template-save "/tmp/preview files/app.conf" test02
```

### Prompt после ошибки

Эти команды доступны только в `inspect-failure>`:

```text
i
ignore
c
continue
a
abort
h
help
?
```

История изменений проекта находится в [CHANGELOG-ru.md](CHANGELOG-ru.md).
