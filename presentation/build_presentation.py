#!/usr/bin/env python3
"""Build the Russian technical presentation with deterministic PPTX styling.

RU: Собирает русскую техническую презентацию с детерминированным оформлением PPTX.
"""

from pathlib import Path
import subprocess
import tempfile
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile


PRESENTATION_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PRESENTATION_DIR.parent
SOURCE = PRESENTATION_DIR / 'inspect-step-technical-overview-ru.md'
OUTPUT = PRESENTATION_DIR / 'inspect-step-technical-overview-ru.pptx'
EXPECTED_TITLES = (
    '«Боль»: printf-debugging вместо debugger',
    'inspect_step - Интерактивная отладка Ansible playbooks',
    'Почему штатных механизмов недостаточно',
    'Что делает и что не делает inspect_step',
    'Архитектура',
    'Жизненный цикл одной task',
    'Карта команд',
    'Интерактивная пауза перед выполнением task',
    'Управление выполнением',
    'Variables: точка, структура, host',
    'Временное изменение variable',
    'Jinja, conditions и сравнение hosts',
    'Lookup: отдельная опасная операция',
    'Preview без выполнения task',
    'Breakpoints и переход go',
    'Продолжение после failed task',
    'Безопасность и --check',
)
EXPECTED_SLIDES = len(EXPECTED_TITLES)

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
for prefix, namespace in NS.items():
    ElementTree.register_namespace(prefix, namespace)


def _qname(prefix, name):
    return '{%s}%s' % (NS[prefix], name)


def _ensure_run_properties(run):
    properties = run.find('a:rPr', NS)
    if properties is None:
        properties = ElementTree.Element(_qname('a', 'rPr'))
        run.insert(0, properties)
    return properties


def _text_runs(container):
    runs = list(container.findall('.//a:r', NS))
    runs.extend(container.findall('.//a:fld', NS))
    return [run for run in runs if run.find('a:t', NS) is not None]


def _set_text_style(container, size, bold=None, color=None):
    """Apply text size and optional emphasis to all DrawingML runs in a container.

    RU: Применяет размер и optional emphasis ко всем DrawingML runs контейнера.

    Args / Параметры:
        container (Element): XML element containing text runs. / XML element с текстом.
        size (int): Font size in hundredths of a point. / Размер в сотых долях point.
        bold (bool or None): Optional bold override. / Необязательное значение bold.
        color (str or None): Optional RGB hex color. / Необязательный RGB hex color.

    Returns / Возвращает:
        None: XML is modified in place. / XML изменяется in place.
    """
    for run in _text_runs(container):
        properties = _ensure_run_properties(run)
        properties.set('sz', str(size))
        if bold is not None:
            properties.set('b', '1' if bold else '0')
        if color is not None:
            for child in list(properties):
                if child.tag in {
                    _qname('a', 'solidFill'),
                    _qname('a', 'gradFill'),
                    _qname('a', 'noFill'),
                }:
                    properties.remove(child)
            fill = ElementTree.Element(_qname('a', 'solidFill'))
            ElementTree.SubElement(
                fill,
                _qname('a', 'srgbClr'),
                {'val': color},
            )
            properties.insert(0, fill)


def _set_table_cell_style(cell_properties):
    """Replace table-cell fills and borders with the neutral project style.

    RU: Заменяет fills и borders ячейки таблицы нейтральным стилем проекта.

    Args / Параметры:
        cell_properties (Element): DrawingML table-cell properties. / Properties ячейки.

    Returns / Возвращает:
        None: XML is modified in place. / XML изменяется in place.
    """
    line_tags = [
        _qname('a', 'lnL'),
        _qname('a', 'lnR'),
        _qname('a', 'lnT'),
        _qname('a', 'lnB'),
    ]
    fill_tags = {
        _qname('a', 'noFill'),
        _qname('a', 'solidFill'),
        _qname('a', 'gradFill'),
        _qname('a', 'blipFill'),
        _qname('a', 'pattFill'),
        _qname('a', 'grpFill'),
    }
    for child in list(cell_properties):
        if child.tag in set(line_tags) | fill_tags:
            cell_properties.remove(child)

    for line_tag in line_tags:
        line = ElementTree.SubElement(cell_properties, line_tag, {'w': '12700'})
        fill = ElementTree.SubElement(line, _qname('a', 'solidFill'))
        ElementTree.SubElement(fill, _qname('a', 'srgbClr'), {'val': 'B7B7B7'})
        ElementTree.SubElement(line, _qname('a', 'prstDash'), {'val': 'solid'})
    ElementTree.SubElement(cell_properties, _qname('a', 'noFill'))


def _style_slide(xml_data):
    """Normalize fonts and table styling in one PowerPoint slide XML document.

    RU: Нормализует fonts и оформление таблиц в XML одного слайда PowerPoint.

    Args / Параметры:
        xml_data (bytes): Serialized slide XML. / Сериализованный XML слайда.

    Returns / Возвращает:
        bytes: Styled XML document. / XML с применённым оформлением.

    Raises / Исключения:
        ParseError: Input is not valid XML. / Входные данные не являются valid XML.
    """
    root = ElementTree.fromstring(xml_data)

    _set_text_style(root, size=1400)

    for shape in root.findall('.//p:sp', NS):
        placeholder = shape.find('./p:nvSpPr/p:nvPr/p:ph', NS)
        if placeholder is not None and placeholder.get('type') in {'title', 'ctrTitle'}:
            _set_text_style(shape, size=2400, bold=True)

    for table in root.findall('.//a:tbl', NS):
        table_properties = table.find('a:tblPr', NS)
        if table_properties is not None:
            for flag in ('firstRow', 'lastRow', 'firstCol', 'lastCol', 'bandRow', 'bandCol'):
                table_properties.set(flag, '0')
            for style in table_properties.findall('a:tableStyleId', NS):
                table_properties.remove(style)

        rows = table.findall('a:tr', NS)
        for row_index, row in enumerate(rows):
            for cell in row.findall('a:tc', NS):
                cell_properties = cell.find('a:tcPr', NS)
                if cell_properties is None:
                    cell_properties = ElementTree.SubElement(cell, _qname('a', 'tcPr'))
                _set_table_cell_style(cell_properties)
                _set_text_style(
                    cell,
                    size=1400,
                    bold=True if row_index == 0 else None,
                    color='000000',
                )

    return ElementTree.tostring(root, encoding='utf-8', xml_declaration=True)


def _style_pptx(source, destination):
    """Rewrite slide XML while copying all other PPTX archive entries unchanged.

    RU: Перезаписывает XML слайдов, копируя остальные entries PPTX без изменений.

    Args / Параметры:
        source (Path): Raw PPTX generated by Pandoc. / Исходный PPTX от Pandoc.
        destination (Path): Styled output PPTX. / Итоговый оформленный PPTX.

    Returns / Возвращает:
        None: The destination archive is created or replaced. / Создаёт итоговый archive.

    Raises / Исключения:
        OSError: Archive files cannot be read or written. / Ошибка чтения или записи.
        BadZipFile: Source is not a valid ZIP/PPTX archive. / Source не является ZIP/PPTX.
    """
    with ZipFile(source) as input_archive, ZipFile(
        destination,
        'w',
        compression=ZIP_DEFLATED,
    ) as output_archive:
        for entry in input_archive.infolist():
            data = input_archive.read(entry.filename)
            if (
                entry.filename.startswith('ppt/slides/slide')
                and entry.filename.endswith('.xml')
            ):
                data = _style_slide(data)
            output_archive.writestr(entry, data)


def _validate_pptx(path):
    """Validate archive integrity, slide order, fonts, and table styling.

    RU: Проверяет archive, порядок слайдов, fonts и оформление таблиц.

    Args / Параметры:
        path (Path): PPTX file to validate. / Проверяемый PPTX.

    Returns / Возвращает:
        None: Successful validation has no return value. / При успехе ничего не возвращает.

    Raises / Исключения:
        RuntimeError: Any required presentation invariant is violated. /
            Нарушен любой обязательный invariant презентации.
        BadZipFile: Input is not a valid ZIP/PPTX archive. / Input не является ZIP/PPTX.
    """
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('The generated PPTX archive is corrupt')

        # EN: ZIP entries sort lexically, so slide10 would otherwise precede slide2.
        # RU: ZIP entries сортируются лексически, поэтому slide10 оказался бы перед slide2.
        slide_names = sorted(
            [
                name
                for name in archive.namelist()
                if name.startswith('ppt/slides/slide')
                and name.endswith('.xml')
            ],
            key=lambda name: int(Path(name).stem[5:]),
        )
        if len(slide_names) != EXPECTED_SLIDES:
            raise RuntimeError(
                'Expected %d slides, found %d' % (EXPECTED_SLIDES, len(slide_names))
            )

        tables = 0
        slide_titles = []
        for slide_name in slide_names:
            root = ElementTree.fromstring(archive.read(slide_name))
            for shape in root.findall('.//p:sp', NS):
                placeholder = shape.find('./p:nvSpPr/p:nvPr/p:ph', NS)
                is_title = (
                    placeholder is not None
                    and placeholder.get('type') in {'title', 'ctrTitle'}
                )
                if is_title:
                    slide_titles.append(
                        ''.join(
                            run.find('a:t', NS).text or ''
                            for run in _text_runs(shape)
                        )
                    )
                for run in _text_runs(shape):
                    properties = _ensure_run_properties(run)
                    expected_size = '2400' if is_title else '1400'
                    if properties.get('sz') != expected_size:
                        raise RuntimeError('Unexpected font size in %s' % slide_name)
                    if is_title and properties.get('b') != '1':
                        raise RuntimeError('Slide title is not bold in %s' % slide_name)

            for table in root.findall('.//a:tbl', NS):
                tables += 1
                table_properties = table.find('a:tblPr', NS)
                if (
                    table_properties is not None
                    and table_properties.find('a:tableStyleId', NS) is not None
                ):
                    raise RuntimeError('A colored table style remains in %s' % slide_name)
                for row_index, row in enumerate(table.findall('a:tr', NS)):
                    for cell in row.findall('a:tc', NS):
                        cell_properties = cell.find('a:tcPr', NS)
                        if (
                            cell_properties is None
                            or cell_properties.find('a:noFill', NS) is None
                        ):
                            raise RuntimeError('A table cell has a fill in %s' % slide_name)
                        for run in _text_runs(cell):
                            properties = _ensure_run_properties(run)
                            if properties.get('sz') != '1400':
                                raise RuntimeError(
                                    'Unexpected table font size in %s' % slide_name
                                )
                            if row_index == 0 and properties.get('b') != '1':
                                raise RuntimeError(
                                    'Table header is not bold in %s' % slide_name
                                )

        if tables != 0:
            raise RuntimeError('Expected no tables, found %d' % tables)
        if tuple(slide_titles) != EXPECTED_TITLES:
            raise RuntimeError(
                'Unexpected slide titles:\n%s'
                % '\n'.join(slide_titles)
            )


def main():
    """Generate, style, validate, and publish the PowerPoint presentation.

    RU: Генерирует, оформляет, проверяет и сохраняет презентацию PowerPoint.

    Returns / Возвращает:
        None: Writes ``OUTPUT`` and prints the slide count. / Записывает ``OUTPUT``.

    Raises / Исключения:
        CalledProcessError: Pandoc generation fails. / Ошибка генерации Pandoc.
        RuntimeError: Generated PPTX fails validation. / Итоговый PPTX не прошёл проверку.
    """
    with tempfile.TemporaryDirectory(prefix='inspect-step-presentation-') as temp_dir:
        raw_pptx = Path(temp_dir) / 'raw.pptx'
        subprocess.run(
            [
                'pandoc',
                str(SOURCE),
                '--resource-path=%s' % PRESENTATION_DIR,
                '--slide-level=1',
                '-f',
                'markdown-implicit_figures',
                '-t',
                'pptx',
                '-o',
                str(raw_pptx),
            ],
            cwd=str(PROJECT_DIR),
            check=True,
        )
        _style_pptx(raw_pptx, OUTPUT)

    _validate_pptx(OUTPUT)
    print('Built %s (%d slides)' % (OUTPUT, EXPECTED_SLIDES))


if __name__ == '__main__':
    main()
