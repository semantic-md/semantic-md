import re

class NoMatch(Exception):
    pass

def match_content(
    vars_map: dict[str, str | None], pattern: str, content: str,
) -> dict[str, str]:
    """
    Collect/apply vars_map to {key} values in pattern against
    content.

    Return newly collected values when pattern matches content
    (empty dict is success with no values) otherwise raise NoMatch.
    """
    ep = r'^\s*' + re.escape(pattern) + r'\s*$'

    # var names are restricted to [a-z][0-9]_
    for var, val in vars_map.items():
        if val is not None:
            ep = ep.replace(r'\{' + var + r'\}', re.escape(val))
            continue
        ep = ep.replace(r'\{' + var + r'\}', '(?P<g' + var + '>.*)', 1)
        ep = ep.replace(r'\{' + var + r'\}', '(?P=g' + var + ')')

    m = re.match(ep, content)
    if not m:
        raise NoMatch()

    return {
        var: m.group('g' + var)
        for var, val in vars_map.items()
        if val is None and 'g' + var in m.groupdict()
    }
