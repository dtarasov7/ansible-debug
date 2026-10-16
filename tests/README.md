# Проверки совместимости

Стратегии самодостаточны: для установки нужен только один `.py` из `strategy_plugins/`.

| Файл | Диапазон ansible-core | Проверенные patch-релизы |
| --- | --- | --- |
| `inspect_step_2_14.py` | 2.14–2.18 | 2.14.18, 2.15.13, 2.16.19, 2.17.14, 2.18.19 |
| `inspect_step_2_19.py` | 2.19–2.20 | 2.19.0, 2.19.13, 2.20.0, 2.20.9 |
| `inspect_step_2_21.py` | 2.21 | 2.21.0, 2.21.4 |

Проверки выполнялись в Docker с Python 3.12 на двух локальных inventory hosts.
Дополнительно проверен запуск `check_compat.py inspect_step_2_21 --check`.
Это тесты интеграции плагина, не сертификация всех возможностей Ansible и collections.
Исходная реализация `inspect_step.py` для 2.12–2.13 служит источником общих команд
и диагностики; изменения распространяются генератором во все варианты.

`check_compat.py` проверяет загрузку стратегии, выражения, запрет/разрешение lookup,
variables, args, watches, loop и with_items, label/index/extended metadata,
item-aware when/args/eval, preview шаблона, результаты на двух hosts,
игнорирование failure, explicit meta и обычное выполнение handler.

`check_control.py` проверяет skip, include run-all с flush_handlers,
возврат к остановкам после include, run! и передачу set в worker.
`check_expressions.py` проверяет границы версий, lookup/query/q,
восстановление lookup loader после ошибки и сохранение недоверенного текста
переменных в движке 2.19+.

## Повторный запуск

Из корня проекта, с Python, совместимым с выбранной версией Ansible:

```bash
python3 -m venv .venv
.venv/bin/pip install 'ansible-core==2.21.4' 'pexpect==4.9.0'
PATH="$PWD/.venv/bin:$PATH" python tests/check_compat.py inspect_step_2_21
PATH="$PWD/.venv/bin:$PATH" python tests/check_control.py inspect_step_2_21
PATH="$PWD/.venv/bin:$PATH" python tests/check_expressions.py inspect_step_2_21
PATH="$PWD/.venv/bin:$PATH" python tests/check_skips.py inspect_step_2_21
PATH="$PWD/.venv/bin:$PATH" python tests/check_tag_order.py inspect_step_2_21
```

Для других версий замените pin и имя стратегии по таблице. Проверки используют
локальные debug/assert/fail/template tasks; их временные файлы и журналы остаются
в `tests/`. Playbook-пример в `example/` не изменяется.

## Обновление самостоятельных файлов

Чтобы не поддерживать вручную четыре копии интерфейса команд, генератор читает
старую реализацию и применяет адаптации внутренних API:

```bash
python3 tests/build_variants.py
```

Изменения совместимости вносите в генератор и повторно запускайте тесты.
При изменении старого файла также пересоздавайте и проверяйте варианты.
В новых реализациях не используются runtime-импорты соседних файлов.

`check_skips.py` проверяет немедленный вывод причин `when`, пустого и смешанного loop,
ручного skip и скрытие результатов `no_log`, включая отсутствие дубликатов.
Проверяются запуск и интерактивное переключение `tag-skips`, фильтрация статических
imports/roles, наследуемых и шаблонных тегов, секций rescue/always, dynamic includes
и roles, бирюзовый цвет и работа при
`display_skipped_hosts=false`. Выполнение без `--step` с включённой и выключенной
диагностикой сравнивается с `linear` по recap на двух hosts.

`check_skips.py` также проверяет порядок вывода между результатами и prompts,
пропуски в конце dynamic include и play, отсутствие истории при переключении.
`check_tag_order.py` проверяет активные/неактивные ветки rescue, always,
пропуски оставшейся обычной ветки после failure, `--start-at-task`, `end_play`
и необработанную ошибку, в том числе разные ветки на двух hosts. Пропуски в конце
списка проверяются до автоматического запуска handlers. Для каждого случая recap
сравнивается с `linear`.

Диагностика пропусков проверена на ansible-core 2.12.10, 2.13.13, 2.14.18,
2.18.19, 2.19.13, 2.20.9 и 2.21.4. Для 2.12–2.13 использовался Python 3.8,
для остальных — Docker с Python 3.12. Существующие интеграции команд и управления
выполнением также прошли на 2.13.13, 2.14.18, 2.18.19, 2.19.13, 2.20.9 и 2.21.4;
на 2.21.4 дополнительно проверен `--check`. Отдельный `check_expressions.py`
требует `init_plugin_loader` и не запускается на 2.14.18; проверки этого скрипта
прошли на 2.18.19, 2.19.13, 2.20.9 и 2.21.4.

## Основания для разделения

- Начиная с 2.14, handlers выполняются через основной iterator; аргумент
  `do_handlers` и отдельный `_do_handler_run` больше не нужны.
- В 2.19 изменились доверие к шаблонам, conditional/lookup API и доступ к raw results.
  `disable_lookups` больше не обеспечивает блокировку. На время синхронной
  команды инспектора lookup loader блокируется с обязательным восстановлением;
  `eval-lookup` выполняется без этой блокировки. Доверенным помечается только
  ввод оператора и содержимое явно выбранного template-файла.
- В 2.21 результаты обрабатываются через `HostTaskResult.utr`.

Сверено с установленными исходниками Ansible и официальными руководствами:
[porting guide 2.19](https://docs.ansible.com/projects/ansible/latest/porting_guides/porting_guide_core_2.19.html),
[porting guide 2.21](https://docs.ansible.com/projects/ansible/latest/porting_guides/porting_guide_core_2.21.html).
