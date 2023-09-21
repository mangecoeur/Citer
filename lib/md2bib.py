"""
Functions to extract bibliographic keys from a BibTeX file, using the
keys used in a Markdown or LaTeX file.

Modified from md2bib.py [1], which is (c) Copyright 2011-2012 by
Joseph Reagle and licensed under the GPLv3.

[1] https://github.com/reagle/pandoc-wrappers/

"""

from collections import OrderedDict
import logging
import re


BIBKEY_PAT = '([.:;,\-\w]+)'


def parse_bibtex(text):
    """Return a dictionary of entry dictionaries, each with a field/value.
    The parser is simple/fast *and* inflexible, unlike the proper but
    slow parsers bibstuff and pyparsing-based parsers.

    """
    entries = OrderedDict()
    key_pat = re.compile('@' + BIBKEY_PAT + '\{(.*),')
    value_pat = re.compile('[\s]*(\w+)[\s]*=[\s]*{(.*)},?')
    for line in text:
        key_match = key_pat.match(line)
        if key_match:
            entry_type = key_match.group(1)
            key = key_match.group(2)
            entries[key] = OrderedDict({'entry_type': entry_type})
            continue
        value_match = value_pat.match(line)
        if value_match:
            field, value = value_match.groups()
            entries[key][field] = value
    return entries


def emit_entry(identifier, values, outfd):
    """Emit a single bibtex entry."""
    outfd.write('@%s{%s,\n' % (values['entry_type'], identifier))
    for field, value in values.items():
        if field != 'entry_type':
            outfd.write('    %s = {%s},\n' % (field, value))
    outfd.write("}\n\n")


def emit_bibliography(entries, outfd):
    """Emit a bibtex file."""
    for identifier, values in entries.items():
        emit_entry(identifier, values, outfd)


def subset_bibliography(entries, keys):
    """Emit a subset of a bibtex file based on bibtex keys."""
    subset = OrderedDict()
    for key in sorted(keys):
        if key in entries:
            subset[key] = entries[key]
        else:
            logging.critical("%s not in entries" % key)
            pass
    return subset


def get_keys_from_document(filename):
    """Return a list of keys used in filename by looking for citations
    like `@citekey`.

    Also look for citations in the
    `\cite*{key}` style, where `*` can be any character or none.

    """
    k_md = '\[@' + BIBKEY_PAT + '\]|(?<!\[)@' + BIBKEY_PAT
    k_latex = '\\cite.?\[?(?:.+?)?\]?\{' + BIBKEY_PAT + '\}'

    text = open(filename, 'r', encoding='utf-8').read()
    md = re.findall(k_md, text)
    md_brackets, md_intext = list(zip(*md))
    md_brackets, md_intext = list(md_brackets), list(md_intext)

    matches = []
    # Split up finds if necessary to deal with [@key0; @key1]
    for f in md_brackets:
        if '@' in f:
            sub_f = f.replace(' ', '').replace('@', '').split(';')
            matches.extend(sub_f)
        elif f != '':
            matches.append(f)

    matches.extend([i for i in md_intext if i != ''])

    latex = re.findall(k_latex, text)
    for f in latex:
        if ',' in f:
            sub_f = [i.strip() for i in f.split(',')]
            matches.extend(sub_f)
        elif f != '':
            matches.append(f)

    logging.debug('Found keys in document: ' + ', '.join(matches))
    return matches


def extract_bibliography(source_doc, source_bib, target_bib):
    # Extract citation keys from source file
    keys = get_keys_from_document(source_doc)
    # Read source bibliography and generate subset
    with open(source_bib, 'r', encoding='utf-8') as f:
        entries = parse_bibtex(f.readlines())
    subset = subset_bibliography(entries, keys)
    # Write extracted subset to new bibliography file
    with open(target_bib, 'w', encoding='utf-8') as f:
        emit_bibliography(subset, f)
