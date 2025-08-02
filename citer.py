import sublime
import sublime_plugin

import sys
import os.path
import string
import re

reloader_name = 'citer.reloader'
reloader_name = 'Citer.' + reloader_name
from imp import reload

# Make sure all dependencies are reloaded on upgrade
if reloader_name in sys.modules:
    reload(sys.modules[reloader_name])

if os.path.dirname(__file__) not in sys.path:
    sys.path.append(os.path.dirname(__file__))

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
COMPLETION_TYPE = None

# Internal Cache globals
_PAPERS = {}
_YAMLBIB_PATH = None
_LST_MOD_TIME = {}
_DOCUMENTS = []
_MENU = None
_CITEKEYS = None
_FORMATTED_INFO = {}  # for formatted paper info


def plugin_loaded():
    """Called directly from sublime on plugin load"""
    refresh_settings()
    refresh_caches()


def plugin_unloaded():
    pass


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


def bibfile_modifed(bib_path):
    global _LST_MOD_TIME
    bib_path = bib_path.strip()
    last_modified_time = os.path.getmtime(bib_path)
    cached_modifed_time = _LST_MOD_TIME.get(bib_path)
    if cached_modifed_time is None or last_modified_time != cached_modifed_time:
        _LST_MOD_TIME[bib_path] = last_modified_time
        return True
    return False


def load_bibfile(bib_path):
    if bib_path is None:
        sublime.status_message("WARNING: No BibTeX file configured for Citer")
        return []

    bib_path = bib_path.strip()
    try:
        with open(bib_path, 'r', encoding="utf-8") as bibfile:
            bp = BibTexParser(bibfile.read(),
                              customization=convert_to_unicode,
                              ignore_nonstandard_types=False)
            return list(bp.get_entry_list())
    except Exception as e:
        sublime.error_message("Error reading BibTeX file: {0}".format(str(e)))
        return []


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
    global COMPLETION_TYPE

    def get_settings(setting, default):
        project_data = sublime.active_window().project_data()
        if setting == 'bibtex_file_path':
            setting = 'bibtex_file'

        if project_data and setting in project_data:
            if setting == 'bibtex_file':
                window = sublime.active_window()
                ref_dir = os.path.dirname(window.project_file_name())
                result = ref_dir + '/' + project_data['bibtex_file']
                return result
            return project_data[setting]
        return settings.get(setting, default)

    settings = sublime.load_settings('Citer.sublime-settings')
    BIBFILE_PATH = get_settings('bibtex_file_path', None)
    SEARCH_IN = get_settings('search_fields', ["author", "title", "year", "id", "abstract"])
    CITATION_FORMAT = get_settings('citation_format', "@%s")
    COMPLETIONS_SCOPES = get_settings('completions_scopes', ['text.html.markdown'])
    EXCLUDED_SCOPES = get_settings('excluded_scopes', [])

    ENABLE_COMPLETIONS = get_settings('enable_completions', True)
    QUICKVIEW_FORMAT = get_settings('quickview_format', '{citekey} - {title}')
    PANDOC_FIX = get_settings('auto_merge_citations', False)
    EXCLUDE = get_settings('hide_other_completions', True)
    # If completion_type is not configured in the setting, `citekey` is the default
    COMPLETION_TYPE = get_settings('completion_type', 'citekey') 


def refresh_caches():
    global _DOCUMENTS
    global _MENU
    global _CITEKEYS
    global _FORMATTED_INFO

    paths = []
    if BIBFILE_PATH is not None:
        if isinstance(BIBFILE_PATH, list):
            paths += [os.path.expandvars(path) for path in BIBFILE_PATH]
        else:
            paths.append(os.path.expandvars(BIBFILE_PATH))
    if _YAMLBIB_PATH is not None:
        paths.append(_YAMLBIB_PATH)

    if len(paths) == 0:
        sublime.status_message("WARNING: No BibTeX file configured for Citer")
    else:
        modified = any(bibfile_modifed(single_path) for single_path in paths)
        if modified:
            _DOCUMENTS = []
            for single_path in paths:
                _DOCUMENTS += load_bibfile(single_path)

    _CITEKEYS = [doc.get('id') for doc in _DOCUMENTS]

    # Build formatted info dictionary with author, year, abstract
    _FORMATTED_INFO = {}
    for doc in _DOCUMENTS:
        citekey = doc.get('id', 'Unknown')
        title = doc.get('title', 'No Title').replace('{', '').replace('}', '')
        year = doc.get('year', 'n.d.')
        abstract = doc.get('abstract', None)

        if doc.get('author') is not None:
            auths = _parse_authors(doc.get('author'))
        else:
            auths = 'Anon'

        formatted_title = string.Formatter().vformat(QUICKVIEW_FORMAT, (), SafeDict(
            citekey=citekey,
            title=title,
            author=auths,
            year=year
        ))

        # Store full info for popup
        _FORMATTED_INFO[citekey] = {
            'title': title,
            'author': auths,
            'year': year,
            'abstract': abstract,
            'formatted_title': formatted_title
        }

    # Build menu from formatted titles
    _MENU = [[info['formatted_title']] for info in _FORMATTED_INFO.values()]
    _MENU = sorted(_MENU)


# Helper function to find citations
def find_citation_at_point(view, point):
    pattern = r'(?<!\w)@([^\s\.,;:?!()\[\]\{\}\'"]+)'
    line_region = view.line(point)
    line_text = view.substr(line_region)

    for match in re.finditer(pattern, line_text):
        start, end = match.span()
        start_abs = line_region.begin() + start
        end_abs = line_region.begin() + end
        if start_abs <= point <= end_abs:
            citekey = match.group(1)
            if citekey in _CITEKEYS:
                return (citekey, sublime.Region(start_abs, end_abs))
    return (None, None)


# An event listener for hover
class CiterHoverEventListener(sublime_plugin.EventListener):
    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT:
            return

        citekey, region = find_citation_at_point(view, point)
        if citekey is None:
            return

        info = _FORMATTED_INFO.get(citekey)
        if not info:
            return

        # Build popup content using .format()
        popup_content = "<b>{0}</b>".format(info['formatted_title'])
        if info['author'] != 'Anon':
            popup_content += "<br><i>Author(s):</i> {0}".format(info['author'])
        if info['year'] != 'n.d.':
            popup_content += "<br><i>Year:</i> {0}".format(info['year'])
        if info['abstract']:
            abstract = info['abstract'].replace('\n', ' ').strip()
            popup_content += "<br><i>Abstract:</i> {0}".format(abstract)

        view.show_popup(popup_content, location=region.begin(), max_width=800, max_height=400)


# This is for Shift+Enter
class CiterShowCitationInfoCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        sel = self.view.sel()
        if len(sel) == 0:
            return

        point = sel[0].begin()
        citekey, region = find_citation_at_point(self.view, point)

        if citekey is None:
            sublime.status_message("No citation found at cursor")
            return

        info = _FORMATTED_INFO.get(citekey)
        if not info:
            sublime.status_message("No information found for citation: {0}".format(citekey))
            return

        popup_content = "<b>{0}</b>".format(info['formatted_title'])
        if info['author'] != 'Anon':
            popup_content += "<br><i>Author(s):</i> {0}".format(info['author'])
        if info['year'] != 'n.d.':
            popup_content += "<br><i>Year:</i> {0}".format(info['year'])
        if info['abstract']:
            abstract = info['abstract'].replace('\n', ' ').strip()
            popup_content += "<br><i>Abstract:</i> {0}".format(abstract)

        self.view.show_popup(popup_content, location=region.begin(), max_width=800, max_height=400)


# SafeDict for missing keys in formatting
class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def _parse_authors(auth):
    """
    PARSE AUTHORS. Formats:
    Single Author: Lastname
    Two Authors: Lastname1 and Lastname2
    Three or More Authors: Lastname1 et al.
    """
    try:
        authors = auth.split(' and ')
        lat = len(authors)
        if lat == 1:
            return authors[0]
        elif lat == 2:
            return authors[0] + " and " + authors[1]
        else:
            return authors[0] + " et al."
    except Exception:
        return auth


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
    current_results_list = []

    def search_keyword(self, search_term):
        results = {}
        for doc in documents():
            for section_name in SEARCH_IN:
                section_text = doc.get(section_name, "")
                if section_text and search_term.lower() in section_text.lower():
                    info = _FORMATTED_INFO.get(doc.get('id'))
                    if info:
                        results[doc.get('id')] = info['formatted_title']

        self.current_results_list = list(results.values())
        self.view.window().show_quick_panel(self.current_results_list, self._paste)

    def run(self, edit):
        refresh_settings()
        self.view.window().show_input_panel("Cite search", "", self.search_keyword, None, None)

    def is_enabled(self):
        return True

    def _paste(self, item):
        if item == -1:
            return
        ent = self.current_results_list[item].split(' ')[0]
        citekey = CITATION_FORMAT % ent
        if PANDOC_FIX:
            self.view.run_command('insert', {'characters': citekey})
            self.view.run_command('citer_combine_citations')
        else:
            self.view.run_command('insert', {'characters': citekey})


class CiterShowKeysCommand(sublime_plugin.TextCommand):
    current_results_list = []

    def run(self, edit):
        refresh_settings()
        ctk = citekeys_menu()
        if len(ctk) > 0:
            self.current_results_list = ctk
            self.view.window().show_quick_panel(self.current_results_list, self._paste)

    def is_enabled(self):
        return True

    def _paste(self, item):
        if item == -1:
            return
        ent = self.current_results_list[item][0].split(' ')[0]
        citekey = CITATION_FORMAT % ent
        if PANDOC_FIX:
            self.view.run_command('insert', {'characters': citekey})
            self.view.run_command('citer_combine_citations')
        else:
            self.view.run_command('insert', {'characters': citekey})


class CiterGetTitleCommand(sublime_plugin.TextCommand):
    current_results_list = []

    def run(self, edit):
        refresh_settings()
        ctk = citekeys_menu()
        if len(ctk) > 0:
            self.current_results_list = ctk
            self.view.window().show_quick_panel(self.current_results_list, self._paste)

    def is_enabled(self):
        return True

    def _paste(self, item):
        if item == -1:
            return
        ent = self.current_results_list[item][0]
        title = ent.split(' - ', 1)[1] if ' - ' in ent else ent
        self.view.run_command('insert', {'characters': title})


class CiterCompleteCitationEventListener(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, loc):
        in_scope = any(view.match_selector(loc[0], scope) for scope in COMPLETIONS_SCOPES)
        ex_scope = any(view.match_selector(loc[0], scope) for scope in EXCLUDED_SCOPES)

        if ENABLE_COMPLETIONS and in_scope and not ex_scope:
            load_yamlbib_path(view)

            search = prefix.replace('@', '').lower()
            results = []
            
            print("COMPLETION_TYPE", COMPLETION_TYPE)
            for key, info in _FORMATTED_INFO.items():
                if search in key.lower():
                    display_text = info['formatted_title']
                    
                    # Determine what to insert based on completion_type setting
                    if COMPLETION_TYPE == 'citekey':
                        # Insert only the formatted citation key
                        insert_text = CITATION_FORMAT % key
                    elif COMPLETION_TYPE == 'title':
                        # Insert only the title
                        insert_text = info['title']
                    elif COMPLETION_TYPE == 'both':
                        # Insert both citation key and title
                        formatted_key = CITATION_FORMAT % key
                        insert_text = "{0} {1}".format(formatted_key, info['title'])
                    else:
                        # Default fallback to citekey
                        insert_text = CITATION_FORMAT % key
                    
                    results.append([display_text, insert_text])

            if EXCLUDE and len(results) > 0:
                return (results, sublime.INHIBIT_WORD_COMPLETIONS)
            return results


class CiterCombineCitationsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        refresh_settings()
        lstpos = self.view.find_all(r'\]\[')
        for i, pos in reversed(list(enumerate(lstpos))):
            self.view.replace(edit, pos, r'; ')
