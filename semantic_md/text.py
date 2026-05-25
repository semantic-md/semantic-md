import re


VAR_NAME = re.compile(r'{\s*(?P<name>[a-z0-9_]+)\s*(?:\|\s*(?P<filter>\w+)\s*)?}')


class NoMatch(Exception):
    pass


def match_content(
    vars_map: dict[str, str | None],
    pattern: str,
    content: str,
) -> dict[str, str]:
    """
    Collect/apply vars_map to {var} and {var|filter} values in pattern against
    content.

    Return newly collected values when pattern matches content
    (empty dict is success with no values) otherwise raise NoMatch.
    """
    var_filters = {}
    ep = re.escape(pattern)

    for m in re.finditer(VAR_NAME, pattern):
        ep = ep.replace(re.escape(m.group(0)), '(?P<g' + m.group('name') + '>.*)', 1)
        var_filters[m.group('name')] = m.group('filter')

    vm = re.match(ep, content)
    if not vm:
        raise NoMatch()

    return {
        var: filter_fns[filt](vm.group('g' + var)) if filt else vm.group('g' + var)
        for var, filt in var_filters.items()
    }


def mixed_fraction(text):
    """
    proof of concept filter fn
    """
    match text.split():
        case [str(p)] if '/' in p:
            n, d = p.split('/')
            return int(n) / int(d)
        case [str(p)]:
            return int(p)
        case [str(p1), str(p2)] if '/' not in p1 and '/' in p2:
            n, d = p2.split('/')
            return int(p1) + int(n) / int(d)
        case _:
            assert 0, f'mixed_fraction failed to parse: {text}'


# FIXME: make possible to extend

filter_fns = {'mixed_fraction': mixed_fraction}


def extract_content_var_filters(content: str) -> dict[str:str|None]:
    """
    Return all {var} and {var|filters} in content.
    """
    return {m.group('name'): m.group('filter') for m in re.finditer(VAR_NAME, content)}
