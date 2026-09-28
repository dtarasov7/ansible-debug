# inspect_step

[English](README.md) | [Русский](README-ru.md)

`inspect_step` — интерактивный strategy plugin для отладки Ansible playbook и ролей до выполнения каждой task. Он расширяет штатную стратегию `linear`.

Текущая версия: **2.1.0**.

Выберите реализацию для установленной версии **ansible-core**:

| ansible-core | Самостоятельный файл / имя стратегии |
| --- | --- |
| 2.12–2.13 | `inspect_step.py` / `inspect_step` (без изменений) |
| 2.14–2.18 | `inspect_step_2_14.py` / `inspect_step_2_14` |
| 2.19–2.20 | `inspect_step_2_19.py` / `inspect_step_2_19` |
| 2.21 | `inspect_step_2_21.py` / `inspect_step_2_21` |

## Основные возможности

- вывод исходного определения текущей task до принятия решения о запуске;
- выполнение, пропуск или продолжение без дальнейших обычных остановок task;
- явное выполнение одной выбранной task с отключённым task-level `no_log`;
- полное выполнение dynamic `include_tasks` или `include_role` с возвратом остановок;
- управление явными meta-actions без показа неявных lifecycle-tasks Ansible;
- плоский или древовидный просмотр tasks и выбор точного breakpoint по ID;
- выполнение до breakpoint по имени task, role или tag через `go`;
- просмотр переменных, вложенных путей, шаблонов, значений конкретного host и аргументов task;
- предварительное вычисление `when` и сравнение Jinja-результатов между hosts task;
- явное вычисление доверенного lookup-выражения один раз для одного выбранного host;
- preview host-specific элементов loop и metadata `loop_control` без выполнения task;
- вычисление expression, `when`, templated-аргументов или template для выбранного item loop;
- просмотр результата предыдущей task с ограничением глубины;
- автоматический вывод наблюдаемых Jinja-выражений на каждой остановке;
- preview результата `ansible.builtin.template` на экране или его локальное сохранение до выполнения;
- ограничение глубины вывода больших mappings и sequences;
- временное изменение переменной для всех hosts play или одного выбранного host;
- явное игнорирование необработанной ошибки task с продолжением playbook;
- маскирование распространённых ключей секретов в безопасных командах просмотра;
- история команд и редактирование строки через Python `readline`, если модуль доступен.

## Требования

- `ansible-core >= 2.12.0, < 2.22`;
- версия Python, поддерживаемая установленным выпуском Ansible;
- интерактивный стандартный ввод для редактирования командной строки.

Каждый новый вариант строго проверяет свой диапазон версий при запуске. Старый `inspect_step.py` по-прежнему предназначен для 2.12–2.13. Поддержка здесь означает совместимость плагина, а не срок сопровождения выпуска Ansible.

## Быстрый старт

Скопируйте соответствующий самостоятельный файл из `strategy_plugins/` в Ansible-проект и настройте путь к plugin:

Для современных версий скопируйте **один соответствующий файл** из таблицы в `strategy_plugins/` и укажите его имя без `.py` в `strategy`. Например, для 2.19–2.20: `strategy: inspect_step_2_19`. Файл самодостаточен; соседние реализации не требуются. Пример ниже с `inspect_step` относится к 2.12–2.13.

```ini
[defaults]
strategy_plugins = ./strategy_plugins
```

Выберите стратегию в play:

```yaml
---
- name: Debug application role
  hosts: web
  strategy: inspect_step

  roles:
    - application
```

Запустите playbook с `--step`:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --step
```

При запуске плагин выводит `inspect_step version 2.1.0` и статус совместимости с Ansible. Перед каждой исполняемой task он показывает её определение и открывает prompt `inspect-step>`.

## Основные команды

```text
r | run                         выполнить текущую task
r! | run!                       выполнить с отключённым task-level no_log
ra | run-all                    выполнить dynamic include целиком и вернуть остановки
s | skip                        пропустить текущую task
c | continue                    выполнить и отключить обычные остановки task
g | go                          выполнять до настроенного breakpoint
w                               повторно показать текущую task
hosts                           показать hosts play после --limit
vars|v|var [SELECTOR] [host=HOST] [depth=N]
                                посмотреть variables; секреты маскируются
vars!|v!|var! [SELECTOR] [host=HOST] [depth=N]
                                посмотреть variables без маскирования
set NAME VALUE [host=HOST]      временно изменить переменную
e | eval JINJA [host=HOST]      вычислить составную Jinja-строку
eval-lookup JINJA [host=HOST]   вычислить один раз с включёнными lookups
eval-all JINJA [diff=true]      вычислить для всех hosts текущей task
when [HOST|all]                 предварительно проверить when
loop [HOST|all] [depth=N]       показать элементы loop с маскированием
loop eval ITEM JINJA [host=HOST]
loop when|args|template ITEM [host=HOST]
                                исследовать item без его выполнения
result [HOST|all] [depth=N]     показать результат предыдущей task
watch add JINJA [host=HOST]     добавить наблюдаемое выражение
tasks [tree] [FILTERS]          показать tasks и иерархию includes
break pick TASK_ID              добавить точный breakpoint из списка tasks
break task REGEX                добавить breakpoint по имени task
a | args                        показать templated-аргументы task
raw                             показать исходные аргументы task
template [HOST]                 показать результат template
template-save FILE [HOST]       сохранить результат template локально
h | help | ?                    показать справку
```

`vars` — основное имя команды, `v` и `var` — её короткие alias. `SELECTOR` может быть точным именем, dot-path, выражением Jinja, `glob=PATTERN` или `regex=REGEXP`. Glob — шаблон для поиска имён переменных верхнего уровня: `*` означает любое количество символов (`v glob=role_*`), `?` — один символ (`v glob=role_?`), `[ab]` — один из указанных символов (`v glob=role_[ab]`). Префикс `glob=` обязателен; квадратные скобки без него означают индексацию Jinja, например `v groups[tg][0]`. Параметры `host=HOST` и `depth=N` необязательны. Суффикс `!` явно отключает маскирование. Вычисленное выражение может раскрыть секрет.

`tasks` показывает статически известные tasks со стабильными в пределах текущего play ID; `tasks tree` дополнительно отображает вложенность roles и includes. Доступны фильтры `host=HOST`, `regex=REGEXP`, `role=NAME` и `tag=TAG`. Потомки dynamic `include_tasks` и `include_role` появляются после их runtime-раскрытия Ansible. Команда `break pick TASK_ID` создаёт точный breakpoint по UUID для выбранной исполняемой task.

`r!` и `run!` выполняют только выбранную task с отключённым task-level `no_log`. Inspector показывает warning, поскольку результаты, аргументы, diffs и секреты могут попасть в stdout и callback logs. Аргументы, независимо помеченные самим модулем как `no_log`, могут остаться замаскированными.

После необработанной ошибки task prompt `inspect-failure>` предлагает `i | ignore` для продолжения с текущим step-режимом, `c | continue` для продолжения без обычных остановок или `a | abort` для сохранения штатного failed-поведения Ansible.

## Check mode

Используйте check mode и diff mode Ansible вместе с inspector, если нужно получить прогноз изменений до обычного запуска:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --check --diff --step
```

Prompts и команды остаются доступными. `r`, `r!`, `c` и `g` ставят tasks в очередь с `ansible_check_mode=True`; `s` вообще не вызывает task. Результат `changed` означает «изменилась бы» только при корректной поддержке check mode модулем. Неподдерживающий его модуль может быть пропущен или вернуть неполные registered data. Check mode не является границей безопасности: `check_mode: false`, controller-side lookups, включая `eval-lookup`, `template-save`, custom plugins, caches и logging всё ещё могут иметь реальные эффекты. Перед использованием `--check` прочитайте подробное руководство.

## Документация

- [Подробное руководство пользователя](UserGuide-ru.md)
- [English user guide](UserGuide.md)
- [Архитектурные диаграммы](diagramms/)
- [Техническая презентация](presentation/inspect-step-technical-overview-ru.md) ([PowerPoint](presentation/inspect-step-technical-overview-ru.pptx))
- [История изменений](CHANGELOG-ru.md)
- [English changelog](CHANGELOG.md)
- [Запускаемый пример с двумя hosts](example/)

## Предупреждение о безопасности

Маскирование секретов является эвристическим. Команды `r!`, `run!`, `eval`, `eval-lookup`, `eval-all`, watches, `raw`, `vars!`, `v!`, `var!`, `loop!`, `result!`, `args!` и preview template могут раскрывать чувствительные данные, а значения, введённые через `set`, остаются в readline history текущего процесса. `vars`, `v` и `var` маскируют секреты по умолчанию. Для выражений `vars`/`v`/`var`, `eval`, `eval-all`, `loop eval` и watches отключены lookup plugins Ansible. `eval-lookup` намеренно включает их для одного выбранного host и перед каждым вычислением выводит warning; lookup выполняется на controller и может читать файлы, запускать команды, обращаться к внешним системам или иметь side effects. Вычисление `when`, templating аргументов task и preview loop, выбранного item или template следуют штатному templating Ansible и также могут выполнить lookup из task. Игнорирование ошибки task меняет её статус в recap, но не отменяет изменения, выполненные на удалённом host до ошибки. Перед использованием inspector с production-системами или секретами прочитайте раздел о безопасности в руководстве пользователя.

## Лицензия

[MIT](LICENSE)

[Проверки совместимости и повторный запуск тестов](tests/README.md).
