import itertools
import re
from collections.abc import Mapping
from math import gcd

from . import convert
from .text import VAR_NAME, NoMatch

PATH_VARIABLE = re.compile(r'^\$([a-z0-9_]+)$')
VALUE_VARIABLE = re.compile(r'^\$([a-z0-9_]+)$')


class CannotRender(NoMatch):
    pass


def _parts(path):
    return [
        part.replace('~1', '/').replace('~0', '~') for part in path.split('/') if part
    ]


def _path_values(value, path, variables):
    if not path:
        yield value, variables
        return

    part, *remaining = path
    match = PATH_VARIABLE.fullmatch(part)
    if match:
        name = match.group(1)
        if isinstance(value, Mapping):
            if name in variables and str(variables[name]) in value:
                key = str(variables[name])
                yield from _path_values(value[key], remaining, variables)
                return
            for key, child in value.items():
                updated = {**variables, name: str(key)}
                yield from _path_values(child, remaining, updated)
        return

    if part == '-':
        if isinstance(value, list):
            for child in value:
                yield from _path_values(child, remaining, variables)
        return

    if isinstance(value, Mapping) and part in value:
        yield from _path_values(value[part], remaining, variables)
    elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
        yield from _path_values(value[int(part)], remaining, variables)


def _bind_value(template, value, variables):
    if isinstance(template, str):
        match = VALUE_VARIABLE.fullmatch(template)
        if match:
            name = match.group(1)
            if name in variables and variables[name] != value:
                return None
            return {**variables, name: value}
    if isinstance(template, Mapping):
        if not isinstance(value, Mapping) or template.keys() != value.keys():
            return None
        current = variables
        for key, child_template in template.items():
            current = _bind_value(child_template, value[key], current)
            if current is None:
                return None
        return current
    if isinstance(template, list):
        if not isinstance(value, list) or len(template) != len(value):
            return None
        current = variables
        for child_template, child_value in zip(template, value):
            current = _bind_value(child_template, child_value, current)
            if current is None:
                return None
        return current
    return variables if template == value else None


def _bind_patch(patch, context, variables):
    candidates = [variables]
    for path, template in (patch or {}).items():
        next_candidates = []
        for candidate in candidates:
            for value, path_variables in _path_values(context, _parts(path), candidate):
                bound = _bind_value(template, value, path_variables)
                if bound is not None:
                    next_candidates.append(bound)
        candidates = next_candidates
    return candidates


def _format_fraction(value):
    number = float(value)
    if number < 0:
        numerator, denominator = min(
            ((round(abs(number) * den), den) for den in (2, 3, 4, 5, 8, 10, 16)),
            key=lambda pair: abs(pair[0] / pair[1] - abs(number)),
        )
        divisor = gcd(numerator, denominator)
        numerator //= divisor
        denominator //= divisor
        if numerator % denominator == 0:
            return str(-(numerator // denominator))
        return f'-{numerator}/{denominator}'
    whole = int(number)
    fraction = abs(number - whole)
    if fraction < 1e-9:
        return str(whole)
    numerator, denominator = min(
        ((round(fraction * den), den) for den in (2, 3, 4, 5, 8, 10, 16)),
        key=lambda pair: abs(pair[0] / pair[1] - fraction),
    )
    divisor = gcd(numerator, denominator)
    numerator //= divisor
    denominator //= divisor
    if whole:
        return f'{whole} {numerator}/{denominator}'
    sign = '-' if number < 0 else ''
    return f'{sign}{numerator}/{denominator}'


def _value_text(value, filt=None):
    if filt == 'mixed_fraction':
        return _format_fraction(value)
    if isinstance(value, (dict, list)):
        raise CannotRender('structured values cannot fill a text variable')
    return str(value)


def _escape_text(value, destination=False, block_start=False):
    if '\n' in value or '\r' in value:
        raise CannotRender('inline values cannot contain line breaks')
    special = r'\`*_{}[]<>&#!()'
    if destination:
        special += ' \t'
    if block_start:
        special += '-+~.='
    return ''.join(f'&#{ord(char)};' if char in special else char for char in value)


def _render_template(template, variables, raw_variables=()):
    def replace(match):
        name, filt = match.group('name', 'filter')
        if name not in variables:
            raise CannotRender(f'no JSON value supplies variable {name!r}')
        value = variables[name]
        line_start = template.rfind('\n', 0, match.start()) + 1
        line_end = template.find('\n', match.end())
        if line_end == -1:
            line_end = len(template)
        before = template[line_start : match.start()]
        after = template[match.end() : line_end]
        if filt == 'md':
            if before.strip() or after.strip() or not isinstance(value, str):
                raise CannotRender(f'variable {name!r} must be a Markdown block')
            return value.rstrip('\n')
        if filt == 'list':
            marker = re.fullmatch(r'(\s*)([-+*]|\d+[.)])\s+', before)
            if not marker or after.strip() or not isinstance(value, list) or not value:
                raise CannotRender(f'variable {name!r} must be a nonempty Markdown list')
            if not all(isinstance(item, str) and item for item in value):
                raise CannotRender(f'items of {name!r} must be nonempty Markdown text')
            indent, leader = marker.groups()
            ordered = leader[0].isdigit()
            start = int(leader[:-1]) if ordered else 0
            rendered = []
            for index, item in enumerate(value):
                item_leader = f'{start + index}{leader[-1]}' if ordered else leader
                continuation = ' ' * (len(indent) + len(item_leader) + 1)
                lines = item.splitlines()
                rendered.append(
                    lines[0]
                    + ''.join(
                        '\n' + continuation + line if line else '\n' for line in lines[1:]
                    )
                )
                if index:
                    rendered[-1] = f'{indent}{item_leader} {rendered[-1]}'
            return '\n'.join(rendered)
        text = _value_text(value, filt)
        if name in raw_variables:
            return text
        destination = bool(re.search(r'\]\(\s*<?[^)]*$', template[: match.start()]))
        return _escape_text(text, destination, block_start=not before.strip())

    return VAR_NAME.sub(replace, template)


def _render_filter_options(rule, context, variables, content):
    patterns = rule.get('filter_match')
    if isinstance(patterns, str):
        patterns = [patterns]
    elif isinstance(patterns, Mapping):
        form = 'singular' if content == '1' else 'plural'
        patterns = [patterns[form]] if form in patterns else list(patterns.values())
    options = []
    for bound in _bind_patch(rule.get('patch_add'), context, variables):
        for pattern in patterns or []:
            values = {**bound}
            values['content'] = content
            try:
                options.append(
                    _render_template(pattern, values, raw_variables=('content',))
                )
            except CannotRender:
                continue
    return options


def _render_submatch_options(rules, context, variables):
    for index, rule in enumerate(rules):
        if 'match' not in rule:
            continue
        terminal_options = []
        for bound in _bind_patch(rule.get('patch_add'), context, variables):
            try:
                terminal_options.append(_render_template(rule['match'], bound))
            except CannotRender:
                continue
        for terminal in terminal_options:
            filtered = [
                rendered
                for preceding in rules[:index]
                if 'filter_match' in preceding
                for rendered in _render_filter_options(
                    preceding, context, variables, terminal
                )
            ]
            yield from filtered or [terminal]


def _render_table(rule, context, variables):
    row_path = rule.get('row_patch_path')
    row_sources = []
    if row_path:
        path_parts = _parts(row_path)
        if path_parts[-1:] == ['-']:
            path_parts.pop()
        collections = list(_path_values(context, path_parts, variables))
        if len(collections) == 1 and isinstance(collections[0][0], list):
            row_sources = [(row, variables, None, row) for row in collections[0][0]]
    else:
        for path, template in (rule.get('row_patch_add') or {}).items():
            path_parts = _parts(path)
            if '-' in path_parts:
                append_index = path_parts.index('-')
                list_values = list(
                    _path_values(context, path_parts[:append_index], variables)
                )
                if len(list_values) == 1 and isinstance(list_values[0][0], list):
                    row_sources = [
                        (row, variables, template, row) for row in list_values[0][0]
                    ]
                    break
            variable_index = next(
                (
                    index
                    for index, part in enumerate(path_parts)
                    if PATH_VARIABLE.fullmatch(part)
                ),
                None,
            )
            if variable_index is not None:
                name = PATH_VARIABLE.fullmatch(path_parts[variable_index]).group(1)
                collections = list(
                    _path_values(context, path_parts[:variable_index], variables)
                )
                if len(collections) == 1 and isinstance(collections[0][0], Mapping):
                    row_sources = [
                        (
                            context,
                            {**collections[0][1], name: str(key)},
                            None,
                            child,
                        )
                        for key, child in collections[0][0].items()
                    ]
                    break
        if not row_sources and rule.get('row_patch_add'):
            raise CannotRender('cannot locate rows described by row_patch_add')
    if not row_sources:
        raise CannotRender(f'cannot locate table rows at {row_path!r}')

    columns = rule['table_match']
    submatches = rule.get('row_submatch') or {}
    rendered_rows = []
    for row_context, row_variables, row_template, row_data in row_sources:
        cell_options = []
        for index, _column in enumerate(columns, 1):
            rules = submatches.get(f'${index}')
            if rules:
                options = list(
                    _render_submatch_options(rules, row_context, row_variables)
                )
            else:
                options = []
            if not options:
                if row_template is not None:
                    direct = _bind_value(row_template, row_data, {})
                    if direct is not None and str(index) in direct:
                        options = [direct[str(index)]]
                if not options:
                    direct = _bind_patch(
                        rule.get('row_patch_add'), row_context, row_variables
                    )
                    options = [
                        bound[str(index)] for bound in direct if str(index) in bound
                    ]
            if not options:
                raise CannotRender(f'no inverse rule can render table column {index}')
            cell_options.append(options)
        rendered_rows.append(list(itertools.product(*cell_options)))

    for table_rows in itertools.product(*rendered_rows) if rendered_rows else [()]:
        lines = [
            _table_line(columns),
            _table_line(['---'] * len(columns)),
            *(_table_line(row) for row in table_rows),
        ]
        yield '\n'.join(lines)


def _table_line(values):
    def escape_cell(value):
        text = str(value)
        if '\n' in text or '\r' in text:
            raise CannotRender('table cells cannot contain line breaks')
        # A pipe is a delimiter only when preceded by an even number of backslashes.
        return re.sub(
            r'(\\*)\|',
            lambda m: m.group(0) if len(m.group(1)) % 2 else m.group(1) + r'\|',
            text,
        )

    return '| ' + ' | '.join(escape_cell(value) for value in values) + ' |'


def _render_match_options(rule, context, variables):
    if 'table_match' in rule:
        yield from _render_table(rule, context, variables)
        return
    for bound in _bind_patch(rule.get('patch_add'), context, variables):
        try:
            yield _render_template(rule['match'], bound)
        except CannotRender:
            continue


def _render_rules(rules, context, variables):
    chunks = ['']
    for rule in rules or []:
        options = []
        try:
            if 'heading_match' in rule:
                options.extend(_render_heading_options(rule, context, variables))
            else:
                options.extend(_render_match_options(rule, context, variables))
        except CannotRender:
            continue
        if not options:
            continue
        chunks = [_join_blocks(prefix, option) for prefix in chunks for option in options]
    return chunks


def _join_blocks(left, right):
    if not left:
        return right
    if not right:
        return left
    return left.rstrip('\n') + '\n\n' + right.lstrip('\n')


def _render_heading_options(rule, context, variables):
    path = rule.get('patch_path') or ''
    selected = (
        list(_path_values(context, _parts(path), variables))
        if path
        else [(context, variables)]
    )
    groups = []
    for child, path_variables in selected:
        if not isinstance(child, Mapping):
            continue
        choices = []
        for bound in _bind_patch(rule.get('patch_add'), child, path_variables):
            try:
                heading = _render_template(rule['heading_match'], bound)
            except CannotRender:
                continue
            body_options = _render_rules(rule.get('children'), child, bound)
            section_options = _render_rules(rule.get('sections'), child, bound)
            for body in body_options:
                for sections in section_options:
                    if (
                        (rule.get('children') or rule.get('sections'))
                        and not body
                        and not sections
                        and not rule.get('patch_add')
                    ):
                        continue
                    output = _join_blocks(_join_blocks(heading, body), sections)
                    choices.append(output)
        if choices:
            groups.append(choices)
    if not groups:
        return []
    outputs = []
    for combination in itertools.product(*groups):
        output = ''
        for blocks in combination:
            output = _join_blocks(output, blocks)
        outputs.append(output)
    return outputs


def to_markdown(json_doc: dict, schema: convert.Schema) -> str:
    definition = schema.definition
    candidates = _render_rules(
        [*(definition.get('children') or []), *(definition.get('sections') or [])],
        json_doc,
        {},
    )
    for candidate in candidates:
        if not candidate.strip():
            continue
        body = candidate.rstrip('\n') + '\n'
        try:
            rendered = convert.md_parse_body(body, schema)
            actual = convert.to_json(rendered, schema)
        except (AssertionError, KeyError, NoMatch, TypeError, ValueError):
            continue
        if actual == json_doc:
            return body
    raise CannotRender(
        'the schema could not produce Markdown that converts to the given JSON'
    )
