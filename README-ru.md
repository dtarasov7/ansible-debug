# inspect_step

[English](README.md) | [Русский](README-ru.md)

`inspect_step` — интерактивный strategy plugin для отладки Ansible playbook и ролей до выполнения каждой task. Он расширяет штатную стратегию `linear`.

Текущая версия: **1.0.0**.

Техническая совместимость: **ansible-core 2.12–2.13**.  
Основная протестированная версия: **ansible-core 2.13.13**.

## Основные возможности

- вывод исходного определения текущей task до принятия решения о запуске;
- выполнение, пропуск или продолжение без дальнейших обычных остановок task;
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

- `ansible-core >= 2.12.0, < 2.14`;
- версия Python, поддерживаемая установленным выпуском Ansible;
- интерактивный стандартный ввод для редактирования командной строки.

При запуске plugin сообщает обнаруженную версию Ansible. Для версий ниже 2.12 выводится warning о неполной совместимости: команды просмотра, которым нужны переменные task, могут быть недоступны. На версии 2.14 и новее запуск сразу завершается с понятным сообщением о несовместимости вместо последующей ошибки внутреннего strategy API.

## Быстрый старт

Скопируйте `strategy_plugins/inspect_step.py` в Ansible-проект и настройте путь к plugin:

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

При запуске плагин выводит `inspect_step version 1.0.0` и статус совместимости с Ansible. Перед каждой исполняемой task он показывает её определение и открывает prompt `inspect-step>`.

## Основные команды

```text
r | run                         выполнить текущую task
s | skip                        пропустить текущую task
c | continue                    выполнить и отключить обычные остановки task
g | go                          выполнять до настроенного breakpoint
w                               повторно показать текущую task
hosts                           показать hosts play после --limit
vars|v [SELECTOR] [host=HOST] [depth=N]
                                посмотреть variables; секреты маскируются
vars!|v! [SELECTOR] [host=HOST] [depth=N]
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
break task REGEX                добавить breakpoint по имени task
args                            показать templated-аргументы task
raw                             показать исходные аргументы task
template [HOST]                 показать результат template
template-save FILE [HOST]       сохранить результат template локально
h | help | ?                    показать справку
```

`vars` — основное имя команды, `v` — её полный короткий alias. `SELECTOR` может быть точным именем, dot-path, glob или явным regexp вида `regex=^role_.*$`. Параметры `host=HOST` и `depth=N` необязательны и работают одинаково с обоими именами. Суффикс `!` явно отключает маскирование.

После необработанной ошибки task prompt `inspect-failure>` предлагает `i | ignore` для продолжения с текущим step-режимом, `c | continue` для продолжения без обычных остановок или `a | abort` для сохранения штатного failed-поведения Ansible.

## Check mode

Используйте check mode и diff mode Ansible вместе с inspector, если нужно получить прогноз изменений до обычного запуска:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --check --diff --step
```

Prompts и команды остаются доступными. `r`, `c` и `g` ставят tasks в очередь с `ansible_check_mode=True`; `s` вообще не вызывает task. Результат `changed` означает «изменилась бы» только при корректной поддержке check mode модулем. Неподдерживающий его модуль может быть пропущен или вернуть неполные registered data. Check mode не является границей безопасности: `check_mode: false`, controller-side lookups, включая `eval-lookup`, `template-save`, custom plugins, caches и logging всё ещё могут иметь реальные эффекты. Перед использованием `--check` прочитайте подробное руководство.

## Документация

- [Подробное руководство пользователя](UserGuide-ru.md)
- [English user guide](UserGuide.md)
- [Архитектурные диаграммы](diagramms/)
- [Техническая презентация](presentation/inspect-step-technical-overview-ru.md) ([PowerPoint](presentation/inspect-step-technical-overview-ru.pptx))
- [История изменений](CHANGELOG-ru.md)
- [English changelog](CHANGELOG.md)
- [Запускаемый пример с двумя hosts](example/)

## Предупреждение о безопасности

Маскирование секретов является эвристическим. Команды `eval`, `eval-lookup`, `eval-all`, watches, `raw`, `vars!`, `v!`, `loop!`, `result!`, `args!` и preview template могут раскрывать чувствительные данные, а значения, введённые через `set`, остаются в readline history текущего процесса. `vars` и его короткий alias `v` маскируют секреты по умолчанию. Для `eval`, `eval-all`, `loop eval` и watches отключены lookup plugins Ansible. `eval-lookup` намеренно включает их для одного выбранного host и перед каждым вычислением выводит warning; lookup выполняется на controller и может читать файлы, запускать команды, обращаться к внешним системам или иметь side effects. Вычисление `when`, templating аргументов task и preview loop, выбранного item или template следуют штатному templating Ansible и также могут выполнить lookup из task. Игнорирование ошибки task меняет её статус в recap, но не отменяет изменения, выполненные на удалённом host до ошибки. Перед использованием inspector с production-системами или секретами прочитайте раздел о безопасности в руководстве пользователя.

## Лицензия

[MIT](LICENSE)
