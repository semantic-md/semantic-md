from urllib.parse import urlparse
import os.path
from json import dump

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
    '--subdirs',
    is_flag=True,
    help='allow accessing semantic-md files in subdirs of SOURCE parent (cwd if SOURCE is -)',
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
    help='allow accessing semantic-md schema files over HTTP',
)
def json(source, destination, subdirs, schema, http):
    """Convert SOURCE.md to DESTINATION.json"""
    src = click.open_file(source, 'r', 'utf-8')
    dst = click.open_file(destination, 'w', 'utf-8')

    front, body = convert.md_parse_front_matter(src.read())

    if not schema:
        part = front['semantic-md']
        partpath, partname = os.path.split(part)

        if httpish(part):
            if not http:
                raise click.UsageError('Use -x to allow HTTP schema downloads')
            raise click.Abort('FIXME: not yet implemented')

        if not subdirs:
            raise click.UsageError('Use -d to allow referencing schemas in subdirs')

        if source == '-':
            parent = os.getcwd()
        else:
            parent = os.path.abspath(os.path.split(source)[0])

            if not os.path.isabs(partpath):
                partpath = os.path.join(parent, partpath)
        if not os.path.abspath(partpath).startswith(parent):
            raise click.UsageError(f'Schema {partpath} is not in a subdir of {parent}')

        schema = os.path.join(partpath, partname)

    s = convert.Schema.read(click.open_file(schema, 'r', 'utf-8').read())

    parsed = convert.md_parse_body(body, s)
    out = convert.to_json(parsed, s)

    dump(out, dst, indent=2)
