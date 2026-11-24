import pytest

from semantic_md import convert
from semantic_md.match import apply_path_vars
from semantic_md.text import NoMatch, match_content


def convert_document(schema_yaml, markdown):
    schema = convert.Schema.read(schema_yaml)
    return convert.to_json(convert.md_parse_body(markdown, schema), schema)


@pytest.mark.parametrize(
    ('pattern', 'content', 'expected'),
    [
        ('Hello', 'Hello', {}),
        ('Hello {name}!', 'Hello world!', {'name': 'world'}),
        ('{name} Recipe', 'Cookie Recipe', {'name': 'Cookie'}),
    ],
)
def test_text_matching_accepts_complete_matches(pattern, content, expected):
    assert match_content({}, pattern, content) == expected


@pytest.mark.parametrize(
    ('pattern', 'content'),
    [
        ('Hello', 'Hello world'),
        ('Hello {name}!', 'Hello world! extra'),
        ('{name} Recipe', 'Cookie Recipe extra'),
    ],
)
def test_text_matching_rejects_trailing_text(pattern, content):
    with pytest.raises(NoMatch):
        match_content({}, pattern, content)


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('2', 2), ('1/2', 0.5), ('2 1/4', 2.25), ('-2', -2), ('0/3', 0)],
)
def test_mixed_fraction_matches_valid_values(text, expected):
    assert match_content({}, '{amount|mixed_fraction}', text) == {'amount': expected}


@pytest.mark.parametrize(
    'text',
    ['', ' ', 'abc', '1/', '/2', '1/0', '1 1/0', '1/2/3', '1 2', '1 2/3 4', '9' * 1000 + '/1'],
)
def test_mixed_fraction_invalid_values_do_not_match(text):
    with pytest.raises(NoMatch):
        match_content({}, '{amount|mixed_fraction}', text)


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ('2 1/4', {'count': 2.25}),
        ('unknown', {'raw': 'unknown'}),
        ('1/0', {'raw': '1/0'}),
    ],
)
def test_mixed_fraction_falls_back_to_next_block_rule(body, expected):
    schema = '''
children:
  - match: "{amount|mixed_fraction}"
    patch_add: {count: $amount}
  - match: "{raw}"
    patch_add: {raw: $raw}
'''
    assert convert_document(schema, body + '\n') == expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [('1/2', {'count': 0.5}), ('unknown', {'raw': 'unknown'}), ('1/0', {'raw': '1/0'})],
)
def test_mixed_fraction_falls_back_to_next_table_submatch(value, expected):
    schema = '''
children:
  - table_match: [Measure]
    row_submatch:
      $1:
        - match: "{amount|mixed_fraction}"
          patch_add: {count: $amount}
        - match: "{raw}"
          patch_add: {raw: $raw}
'''
    assert convert_document(schema, f'| Measure |\n| --- |\n| {value} |\n') == expected


def test_mixed_fraction_without_alternative_reports_unmatched_block():
    schema = '''
children:
  - match: "{amount|mixed_fraction}"
    patch_add: {count: $amount}
'''
    with pytest.raises(NoMatch, match='line 1'):
        convert_document(schema, 'not a number\n')


@pytest.mark.parametrize(
    ('schema', 'markdown'),
    [
        ('children:\n  - match: "Hello"\n', 'Hello world\n'),
        ('sections:\n  - heading_match: "# Hello"\n', '# Hello world\n'),
        ('children:\n  - match: "![Picture](img.png)"\n', '![Picture](img.png-extra)\n'),
    ],
)
def test_document_rules_reject_prefix_matches(schema, markdown):
    with pytest.raises(NoMatch):
        convert_document(schema, markdown)


@pytest.mark.parametrize('children', ['', '    children: []\n'])
def test_heading_without_children(children):
    schema = (
        'sections:\n'
        '  - heading_match: "# Item {id}"\n'
        '    patch_path: items/$id\n'
        '    patch_add: {name: $id}\n'
        + children
    )
    assert convert_document(schema, '# Item first\n\n# Item second\n') == {
        'items': {'first': {'name': 'first'}, 'second': {'name': 'second'}}
    }


def test_heading_with_sections_but_no_children():
    schema = '''
sections:
  - heading_match: "# Group {group}"
    patch_path: groups/$group
    sections:
      - heading_match: "## Item {item}"
        patch_add: {item: $item}
'''
    assert convert_document(schema, '# Group one\n\n## Item two\n') == {
        'groups': {'one': {'item': 'two'}}
    }


@pytest.mark.parametrize(
    ('schema', 'markdown'),
    [
        ('sections:\n  - heading_match: "# Title"\n', '## Title\n'),
        (
            (
                'sections:\n'
                '  - heading_match: "# Parent"\n'
                '    sections:\n'
                '      - heading_match: "## Title"\n'
            ),
            '# Parent\n\n### Title\n',
        ),
        (
            (
                'sections:\n'
                '  - heading_match: "# Parent"\n'
                '    children:\n'
                '      - match: "## Title"\n'
            ),
            '# Parent\n\n### Title\n',
        ),
        ('children:\n  - match: "## Title"\n', '# Title\n'),
    ],
)
def test_heading_level_mismatch_is_rejected(schema, markdown):
    with pytest.raises(NoMatch):
        convert_document(schema, markdown)


def test_heading_level_selects_correct_nested_rule():
    schema = '''
sections:
  - heading_match: "# Parent"
    sections:
      - heading_match: "## Item"
        patch_add: {kind: section}
    children:
      - match: "### Item"
        patch_add: {kind: child}
'''
    assert convert_document(schema, '# Parent\n\n## Item\n') == {'kind': 'section'}
    assert convert_document(schema, '# Parent\n\n### Item\n') == {'kind': 'child'}


def test_heading_levels_in_multiblock_match():
    schema = '''
children:
  - match: |
      ## Method

      1. {steps|list}
    patch_add: {steps: $steps}
'''
    assert convert_document(schema, '## Method\n\n1. First\n') == {'steps': ['First']}
    with pytest.raises(NoMatch):
        convert_document(schema, '### Method\n\n1. First\n')


@pytest.mark.parametrize(
    ('body', 'expected'),
    [
        ('A paragraph.', 'A paragraph.\n'),
        ('First paragraph.\n\nLast paragraph.\n', 'First paragraph.\n\nLast paragraph.\n'),
        ('First paragraph.\n\nLast paragraph.\n\n', 'First paragraph.\n\nLast paragraph.\n'),
        ('First paragraph.\n\n- One\n- Two\n', 'First paragraph.\n\n- One\n- Two\n'),
        ('> Quote\n', '> Quote\n'),
        ('```\ncode\n```\n', '```\ncode\n```\n'),
    ],
)
def test_md_capture_at_document_end(body, expected):
    schema = '''
children:
  - match: "{description|md}"
    patch_add: {description: $description}
'''
    assert convert_document(schema, body) == {'description': expected}


def test_md_capture_stops_before_a_heading():
    schema = '''
sections:
  - heading_match: "# Item {name}"
    patch_path: items/$name
    children:
      - match: "{description|md}"
        patch_add: {description: $description}
'''
    document = '# Item first\n\nFirst description.\n\n# Item second\n\nLast description.\n'
    assert convert_document(schema, document) == {
        'items': {
            'first': {'description': 'First description.\n'},
            'second': {'description': 'Last description.\n'},
        }
    }


def test_md_capture_stops_before_a_table():
    schema = '''
children:
  - match: "{description|md}"
    patch_add: {description: $description}
  - table_match: [Name]
    row_patch_add: {name: $1}
'''
    assert convert_document(schema, 'Description.\n\n| Name |\n| --- |\n| value |\n') == {
        'description': 'Description.\n',
        'name': 'value',
    }


def test_empty_md_capture_does_not_consume_a_heading():
    schema = '''
children:
  - match: "{description|md}"
    patch_add: {description: $description}
sections:
  - heading_match: "# Heading"
    patch_add: {matched: true}
'''
    assert convert_document(schema, '# Heading\n') == {'matched': True}


def test_table_headers_must_match():
    schema = '''
children:
  - table_match: [Name, Label]
    row_patch_add: {result: $1}
'''
    assert convert_document(schema, '| Name | Label |\n| --- | --- |\n| a | b |\n') == {
        'result': 'a'
    }
    for header in ['| Names | Label |', '| Name | Other |']:
        with pytest.raises(NoMatch):
            convert_document(schema, f'{header}\n| --- | --- |\n| a | b |\n')


def test_path_substitution_escapes_once_without_expanding_captured_variables():
    assert apply_path_vars(
        'items/$id/$other/$missing',
        {'id': 'a/~1/$other', 'other': 'x/y'},
    ) == 'items/a~1~01~1$other/x~1y/$missing'


@pytest.mark.parametrize('key', ['a/b~c', '~1', '-', '$other'])
def test_heading_and_patch_paths_escape_captured_values(key):
    schema = '''
sections:
  - heading_match: "# Item {id}"
    patch_path: items/$id
    patch_add:
      "nested/$id": $id
'''
    assert convert_document(schema, f'# Item {key}\n') == {
        'items': {key: {'nested': {key: key}}}
    }


@pytest.mark.parametrize('key', ['a/b~c', '~1', '-'])
def test_table_row_paths_escape_captured_values(key):
    schema = '''
children:
  - table_match: [Name, Value]
    row_patch_path: rows/$1
    row_patch_add:
      "values/$1": $2
    row_submatch:
      $2:
        - match: "{value}"
          patch_add:
            "submatches/$1": $value
'''
    assert convert_document(schema, f'| Name | Value |\n| --- | --- |\n| {key} | text |\n') == {
        'rows': {key: {'values': {key: 'text'}, 'submatches': {key: 'text'}}}
    }


def test_append_paths_with_escaped_parent():
    schema = '''
sections:
  - heading_match: "# Group {id}"
    patch_path: groups/$id/-
    patch_add:
      "names/$id/-": $id
    children:
      - table_match: [Name]
        row_patch_path: "rows/$1/-"
        row_patch_add: {name: $1}
'''
    document = '# Group a/b~c\n\n| Name |\n| --- |\n| d/e~f |\n'
    assert convert_document(schema, document) == {
        'groups': {
            'a/b~c': [
                {'names': {'a/b~c': ['a/b~c']}, 'rows': {'d/e~f': [{'name': 'd/e~f'}]}}
            ]
        }
    }
