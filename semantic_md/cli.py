import os.path
from json import dump, dumps, load
from urllib.parse import urlparse

import click

from semantic_md import convert


def httpish(s):
    """return True if s looks like an HTTP(S) url"""
    try:
        r = urlparse(s)
        return r.scheme.startswith('http') and r.netloc
    except ValueError:
        return False


@click.group()
def cli():
    pass


@cli.command()
@click.argument('source', default='-')
@click.argument('destination', default='-')
@click.option(
    '-d',
    '--schema-dir',
    help='allow front matter semantic-md schema files found under DIR (defaults '
    'to parent of SOURCE)',
    metavar='DIR',
)
@click.option(
    '-s',
    '--schema',
    help='specify semantic-md schema (ignore any given in front matter)',
    metavar='SCHEMA',
)
@click.option(
    '-x',
    '--http',
    is_flag=True,
    help='allow front matter semantic-md schema file HTTP URLs',
)
def json(source, destination, schema_dir, schema, http):
    """Convert SOURCE.md to DESTINATION.json"""
    src = click.open_file(source, 'r', 'utf-8')
    dst = click.open_file(destination, 'w', 'utf-8')

    front, body = convert.md_parse_front_matter(src.read(), allow_missing=bool(schema))

    if not schema:
        part = front.get('semantic-md', '')
        part_path, part_name = os.path.split(part)

        if not part_name:
            raise click.UsageError(
                'Schema must be present in front matter or given with -s'
            )

        if httpish(part):
            if not http:
                raise click.UsageError('Use -x to allow HTTP schema downloads')
            raise click.UsageError('FIXME: HTTP schemas not yet implemented')

        if source == '-':
            if not schema_dir:
                raise click.UsageError(
                    'Use -d=DIR to allow referencing schemas under DIR'
                )
            if not os.path.isabs(part_path):
                raise click.UsageError(
                    'Relative schemas in front matter are not supported on stdin'
                )
        elif not schema_dir:
            schema_dir = os.path.split(source)[0]
            if not os.path.isabs(part_path):
                part_path = os.path.join(schema_dir, part_path)

        schema_dir = os.path.abspath(schema_dir)

        if not os.path.abspath(part_path).startswith(schema_dir):
            raise click.UsageError(
                f'Schema {part_path} is not in a subdir of {schema_dir}'
            )

        schema = os.path.join(part_path, part_name)

    s = convert.Schema.read(click.open_file(schema, 'r', 'utf-8').read())

    parsed = convert.md_parse_body(body, s)
    out = convert.to_json(parsed, s)

    dump(out, dst, indent=2, ensure_ascii=False)


@cli.command('md')
@click.argument('source', default='-')
@click.argument('destination', default='-')
@click.option(
    '-s',
    '--schema',
    required=True,
    help='specify semantic-md schema',
    metavar='SCHEMA',
)
def markdown(source, destination, schema):
    """Convert SOURCE.json to DESTINATION.md"""
    with click.open_file(source, 'r', 'utf-8') as src:
        json_doc = load(src)
    with click.open_file(schema, 'r', 'utf-8') as schema_file:
        parsed_schema = convert.Schema.read(schema_file.read())

    try:
        body = convert.to_markdown(json_doc, parsed_schema)
    except convert.NoMatch as exc:
        raise click.ClickException(str(exc)) from exc

    if destination == '-':
        schema_reference = os.path.abspath(schema)
    else:
        schema_reference = os.path.relpath(
            os.path.abspath(schema), os.path.dirname(os.path.abspath(destination))
        )
    with click.open_file(destination, 'w', 'utf-8') as dst:
        dst.write(f'---\nsemantic-md: {dumps(schema_reference)}\n---\n\n')
        dst.write(body)
