from __future__ import print_function, absolute_import, division
import sublime
import sublime_plugin

import sys
import os.path
import string, re

# ST3 loads each package as a module, so it needs an extra prefix

reloader_name = 'citer.reloader'
reloader_name = 'Citer.' + reloader_name
from imp import reload

# Make sure all dependencies are reloaded on upgrade
if reloader_name in sys.modules:
    reload(sys.modules[reloader_name])

if os.path.dirname(__file__) not in sys.path:
    sys.path.append(os.path.dirname(__file__))
    #sys.path.append(os.path.join(os.path.dirname(__file__), 'python-bibtexparser'))


from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import convert_to_unicode


# settings cache globals
BIBFILE_PATH = None
SEARCH_IN = None
CITATION_FORMAT = None
QUICKVIEW_FORMAT = None
ENABLE_COMPLETIONS = None
COMPLETIONS_SCOPES = None
EXCLUDED_SCOPES = None

PANDOC_FIX = None
EXCLUDE = None

# Internal Cache globals
_PAPERS = {}
_YAMLBIB_PATH = None
_LST_MOD_TIME = {}
_DOCUMENTS = []
_MENU = None
_CITEKEYS = None


def plugin_loaded():
    """Called directly from sublime on plugin load
    """
    refresh_settings()
    refresh_caches()


def plugin_unloaded():
    pass

# Papers


def load_yamlbib_path(view):
    global _PAPERS
    global _YAMLBIB_PATH

    filename = view.file_name()
    if filename not in _PAPERS:
        _PAPERS[filename] = Paper(view)

    _YAMLBIB_PATH = _PAPERS[filename].bibpath()


class Paper:

    _filepath = None
    _bibpath = None
    _modified = None

    def __init__(self, view):
        self.view = view
        self._filepath = view.file_name()

    def bibpath(self):

        modified = os.path.getmtime(self._filepath)
        if self._modified != modified:
            self._modified = modified
            self._bibpath = None

            text = self.view.substr(sublime.Region(0, self.view.size()))
            yamlP = re.compile(r'^---$.*?((^---$)|(^\.\.\.$))', re.MULTILINE | re.DOTALL)
            yamlMatch = yamlP.search(text)

            if yamlMatch:

                bibP = re.compile(r'^bibliography:', re.MULTILINE)
                bibMatch = bibP.search(yamlMatch.group())

                if bibMatch:

                    text = yamlMatch.group()[bibMatch.end():]
                    pathP = re.compile(r'\S+')
                    pathMatch = pathP.search(text)

                    if pathMatch:

                        folder = os.path.dirname(os.path.realpath(self._filepath))
                        self._bibpath = os.path.join(folder, pathMatch.group())

        return self._bibpath

# Bibfiles


def bibfile_modifed(bib_path):
    global _LST_MOD_TIME
    bib_path = bib_path.strip()
    last_modified_time = os.path.getmtime(bib_path)
    cached_modifed_time = _LST_MOD_TIME.get(bib_path)
    if cached_modifed_time is None or last_modified_time != cached_modifed_time:
        _LST_MOD_TIME[bib_path] = last_modified_time
        return True
    else:
        return False


def load_bibfile(bib_path):
    if bib_path is None:
        sublime.status_message("WARNING: No BibTex file configured for Citer")
        return {}

    bib_path = bib_path.strip()
    with open(bib_path, 'r', encoding="utf-8") as bibfile:
        bp = BibTexParser(bibfile.read(),
                          customization=convert_to_unicode,
                          ignore_nonstandard_types=False)
        return list(bp.get_entry_list())


def refresh_settings():
    global BIBFILE_PATH
    global SEARCH_IN
    global CITATION_FORMAT
    global COMPLETIONS_SCOPES
    global EXCLUDED_SCOPES

    global ENABLE_COMPLETIONS
    global EXCLUDE
    global PANDOC_FIX
    global QUICKVIEW_FORMAT

    def get_settings(setting, default):
        project_data = sublime.active_window().project_data()
        if project_data and setting in project_data:
            return project_data[setting]
        else:
            return settings.get(setting, default)

    settings = sublime.load_settings('Citer.sublime-settings')
    BIBFILE_PATH = get_settings('bibtex_file_path', None)
    SEARCH_IN = get_settings('search_fields', ["author", "title", "year", "id"])
    CITATION_FORMAT = get_settings('citation_format', "@%s")
    COMPLETIONS_SCOPES = get_settings('completions_scopes', ['text.html.markdown'])
    EXCLUDED_SCOPES = get_settings('excluded_scopes', [])

    ENABLE_COMPLETIONS = get_settings('enable_completions', True)
    QUICKVIEW_FORMAT = get_settings('quickview_format', '{citekey} - {title}')
    PANDOC_FIX = get_settings('auto_merge_citations', False)
    EXCLUDE = get_settings('hide_other_completions', True)


def refresh_caches():
    global _DOCUMENTS
    global _MENU
    global _CITEKEYS
    paths = []
    if BIBFILE_PATH is not None:
        if isinstance(BIBFILE_PATH, list):
            paths += [os.path.expandvars(path) for path in BIBFILE_PATH]
        else:
            paths.append(os.path.expandvars(BIBFILE_PATH))
    if _YAMLBIB_PATH is not None:
        paths.append(_YAMLBIB_PATH)

    if len(paths) == 0:
        sublime.status_message("WARNING: No BibTex file configured for Citer")
    else:
        # To avoid duplicate entries, if any bibfiles modified, reload all of them
        modified = False
        for single_path in paths:
            modified = modified or bibfile_modifed(single_path)
        if modified:
            _DOCUMENTS = []
            for single_path in paths:
                _DOCUMENTS += load_bibfile(single_path)

    _CITEKEYS = [doc.get('id') for doc in _DOCUMENTS]
    _MENU = _make_citekey_menu_list(_DOCUMENTS)


# Do some fancy build to get a sane list in the UI
class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def _parse_authors(auth):
    """
    PARSE AUTHORS. Formats:
    Single Author: Lastname
    Two Authors: Lastname1 and Lastname2
    Three or More Authors: Lastname 1 et al.
    """
    try:
        authors = auth.split(' and ')
        lat = len(authors)
        if lat == 1:
            authors_abbr = authors[0]
        elif lat == 2:
            authors_abbr = authors[0] + " and " + authors[1]
        else:
            authors_abbr = authors[0] + " et. al"
    except:
        authors_abbr = auth
    return authors_abbr


def _make_citekey_menu_list(bibdocs):
    citekeys = []
    for doc in bibdocs:
        menu_entry = []

        if doc.get('author') is not None:
            auths = _parse_authors(doc.get('author'))
        else:
            auths = 'Anon'
        title = string.Formatter().vformat(QUICKVIEW_FORMAT, (),
                                           SafeDict(
                                                    citekey=doc.get('id'),
                                                    title=doc.get('title'),
                                                    author=auths,
                                                    year=doc.get('year')
                                                    )
                                           )
        # title = QUICKVIEW_FORMAT.format(
        #     citekey=doc.get('id'), title=doc.get('title'))
        menu_entry.append(title)
        citekeys.append(menu_entry)
    citekeys = sorted(citekeys)
    return citekeys


def documents():
    refresh_caches()
    return _DOCUMENTS


def citekeys_menu():
    refresh_caches()
    return _MENU


def citekeys_list():
    refresh_caches()
    return _CITEKEYS


class CiterSearchCommand(sublime_plugin.TextCommand):

    """
    """
    current_results_list = []

    def search_keyword(self, search_term):
        results = {}
        for doc in documents():
            for section_name in SEARCH_IN:
                section_text = doc.get(section_name)
                if section_text and search_term.lower() in section_text.lower():
                    txt = QUICKVIEW_FORMAT.format(
                        citekey=doc.get('id'), title=doc.get('title'))
                    # ensure we never have duplicates
                    results[doc.get('id')] = txt

        self.current_results_list = list(results.values())
        self.view.window().show_quick_panel(
            self.current_results_list, self._paste)

    def run(self, edit):
        refresh_settings()
        self.view.window().show_input_panel(
            "Cite search", "", self.search_keyword, None, None)

    def is_enabled(self):
        """Determines if the command is enabled
        """
        return True

    def _paste(self, item):
        """Paste item into buffer
        """

        if item == -1:
            return
        ent = self.current_results_list[item]
        ent = ent.split(' ')[0]
        citekey = CITATION_FORMAT % ent
        if PANDOC_FIX:
            self.view.run_command('insert', {'characters': citekey})
            self.view.run_command('citer_combine_citations')
        else:
            self.view.run_command('insert', {'characters': citekey})


class CiterShowKeysCommand(sublime_plugin.TextCommand):

    """
    """
    current_results_list = []

    def run(self, edit):
        refresh_settings()
        ctk = citekeys_menu()
        if len(ctk) > 0:
            self.current_results_list = ctk
            self.view.window().show_quick_panel(self.current_results_list,
                                                self._paste)

    def is_enabled(self):
        """Determines if the command is enabled
        """
        return True

    def _paste(self, item):
        """Paste item into buffer
        """
        if item == -1:
            return
        ent = self.current_results_list[item][0]
        ent = ent.split(' ')[0]
        citekey = CITATION_FORMAT % ent
        if PANDOC_FIX:
            self.view.run_command('insert', {'characters': citekey})
            self.view.run_command('citer_combine_citations')
        else:
            self.view.run_command('insert', {'characters': citekey})


class CiterGetTitleCommand(sublime_plugin.TextCommand):

    """
    """
    current_results_list = []

    def run(self, edit):
        refresh_settings()
        ctk = citekeys_menu()
        if len(ctk) > 0:
            self.current_results_list = ctk
            self.view.window().show_quick_panel(self.current_results_list,
                                                self._paste)

    def is_enabled(self):
        """Determines if the command is enabled
        """
        return True

    def _paste(self, item):
        """Paste item into buffer
        """
        if item == -1:
            return
        ent = self.current_results_list[item][0]
        title = ent.split(' - ', 1)[1]
        self.view.run_command('insert', {'characters': title})


class CiterCompleteCitationEventListener(sublime_plugin.EventListener):

    """docstring for CiterCompleteCitationEventListener"""

    def on_query_completions(self, view, prefix, loc):

        in_scope = any(view.match_selector(loc[0], scope) for scope in COMPLETIONS_SCOPES)
        ex_scope = any(view.match_selector(loc[0], scope) for scope in EXCLUDED_SCOPES)

        if ENABLE_COMPLETIONS and in_scope and not ex_scope:
            load_yamlbib_path(view)

            search = prefix.replace('@', '').lower()

            results = [[key, key] for key in citekeys_list() if search in key.lower()]

            if EXCLUDE and len(results) > 0:
                return (results, sublime.INHIBIT_WORD_COMPLETIONS)
            else:
                return results


class CiterCombineCitationsCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        refresh_settings()
        lstpos = self.view.find_all(r'\]\[')
        for i, pos in reversed(list(enumerate(lstpos))):
            self.view.replace(edit, pos, r'; ')
