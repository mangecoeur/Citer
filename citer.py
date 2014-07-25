from __future__ import print_function, absolute_import, division
import sublime
import sublime_plugin

import sys
import os.path

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


# cache values in here for moar speedy
BIBFILE_PATH = None
SEARCH_IN = None
CITATION_FORMAT = None
LST_MOD_TIME = None
QUICKVIEW_FORMAT = "{citekey} - {title}"  # this could be configurable
ENABLE_COMPLETIONS = None
COMPLETIONS_SCOPES = None

_EXCLUDE = None

_DOCUMENTS = []
_MENU = None
_CITEKEYS = None


def plugin_loaded():
    """Called directly from sublime on plugin load
    """
    global BIBFILE_PATH
    global SEARCH_IN
    global CITATION_FORMAT
    global COMPLETIONS_SCOPES
    global ENABLE_COMPLETIONS
    global _EXCLUDE

    settings = sublime.load_settings('Citer.sublime-settings')
    BIBFILE_PATH = settings.get('bibtex_file_path')
    if BIBFILE_PATH is None or BIBFILE_PATH == '':
        sublime.status_message("WARNING: No bitex file configured for Citer")
    SEARCH_IN = settings.get('search_fields', ["author", "title", "year", "id"])
    CITATION_FORMAT = settings.get('citation_format', "@%s")
    COMPLETIONS_SCOPES = settings.get('completions_scopes', ['text.html.markdown'])
    ENABLE_COMPLETIONS = settings.get('enable_completions', True)
    _EXCLUDE = settings.get('hide_other_completions', True)
    refresh_caches()


def plugin_unloaded():
    pass


def refresh_caches():
    global LST_MOD_TIME
    global _DOCUMENTS
    global _MENU
    global _CITEKEYS

    last_modified_time = os.path.getmtime(BIBFILE_PATH)

    if LST_MOD_TIME is None or last_modified_time != LST_MOD_TIME:

        with open(BIBFILE_PATH, 'r', encoding="utf-8") as bibfile:
            bp = BibTexParser(bibfile.read(), customization=convert_to_unicode)
            _DOCUMENTS = list(bp.get_entry_list())
            _MENU = _make_citekey_menu_list(_DOCUMENTS)
            _CITEKEYS = [doc.get('id') for doc in _DOCUMENTS]


# Do some fancy build to get a sane list in the UI
def _make_citekey_menu_list(bibdocs):
    citekeys = []
    for doc in bibdocs:
        menu_entry = []
        # if len(doc.get('title')) > 90:
        #    title = doc.get('id') + ' - ' + doc.get('title')[0:90]
        #    menu_entry.append(title)
        #    menu_entry.append('  ' + doc.get('title')[90:])
        # else:
        title = QUICKVIEW_FORMAT.format(
            citekey=doc.get('id'), title=doc.get('title'))
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
        self.view.run_command('insert', {'characters': citekey})


class CiterShowKeysCommand(sublime_plugin.TextCommand):

    """
    """
    current_results_list = []

    def run(self, edit):
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
        self.view.run_command('insert', {'characters': citekey})


class CiterGetTitleCommand(sublime_plugin.TextCommand):
    """
    """
    current_results_list = []

    def run(self, edit):
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
        if ENABLE_COMPLETIONS and any(view.match_selector(loc[0],
                                                          scope) for scope in COMPLETIONS_SCOPES):
            search = prefix.replace('@', '').lower()

            results = [[key, key] for key in citekeys_list() if search in key.lower()]

            if _EXCLUDE and len(results) > 0:
                return (results, sublime.INHIBIT_WORD_COMPLETIONS)
            else:
                return results
