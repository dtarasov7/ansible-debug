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
Исходная реализация `inspect_step.py` для 2.12–2.13 не изменена.

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
