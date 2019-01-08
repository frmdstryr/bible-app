# -*- coding: utf-8 -*-
'''
Copyright (c) 2017, Jairus Martin.

Distributed under the terms of the MIT License.

The full license is in the file COPYING.txt, distributed with this software.

Created on July 12, 2017

@author: jrm
'''
import os
import io
import json
import msgpack

#: Escape
from HTMLParser import HTMLParser
html = HTMLParser()

from atom.api import (
    Atom, Unicode, Long, Dict, Enum, Typed, ForwardInstance, Instance, List, Int, Bool, observe
)
from enamlnative.android.app import AndroidApplication
from enamlnative.core.http import AsyncHttpClient


def save_unescape(text):
    #: Apparently this blows up on some versons
    try:
        return html.unescape(text.decode('utf8'))
    except UnicodeDecodeError:
        return text

class Verse(Atom):
    number = Int()
    text = Unicode()


class Chapter(Atom):
    number = Int()
    verses = List(Verse)
    source = Dict()

    def __init__(self, number, verses):
        super(Chapter, self).__init__(number=int(number), source=verses)

    def _default_verses(self):
        return sorted([Verse(
                            number=int(v),
                            text=save_unescape(self.source[v]))
                            for v in self.source],
                            key=self._sort)

    def _sort(self, v):
        return v.number


class Book(Atom):
    name = Unicode()
    abbrev = Unicode()
    chapters = List(Chapter)
    source = Dict()

    def __init__(self, book):
        super(Book, self).__init__(source=book)

    def _default_name(self):
        return self.source['book']

    def _default_abbrev(self):
        return self.source['abbrev']

    def _default_chapters(self):
        return [Chapter(*c.items()[0]) for c in self.source['chapters']]


class Version(Atom):
    #: Name
    name = Unicode()

    #: Key
    key = Unicode()

    #: Language
    language = Unicode()

    #: Download url
    url = Unicode()

    #: Local path on disk
    path = Unicode()

    #: If the file was downloaded
    downloaded = Bool()

    #: Download progress
    progress = Int()
    status = Unicode()
    downloading = Bool()
    _total_bytes = Int(1)
    _bytes = Long()

    client = Instance(AsyncHttpClient,())

    def _default_url(self):
        return u"https://github.com/thiagobodruk/bible/raw/master/json/{}.json".format(self.key)

    def _default_path(self):
        assets = os.path.dirname(os.path.dirname(__file__))
        key = os.path.splitext(os.path.split(self.url)[-1])[0]
        return os.path.join(assets, 'downloads', "{}.msgp".format(key))

    def _default_downloaded(self):
        return os.path.exists(self.path)

    _buffer = Instance(io.BytesIO,())

    def download(self):
        self.status = u"Downloading {}...".format(self.name)
        self.downloading = True
        f = self.client.fetch(self.url,self._handle_response,
                          streaming_callback=self._stream_data)

        #: Watch
        f.request.response.observe('progress', self._update_progress)

    def _update_progress(self, change):
        #: Bind response progress to this progress
        self.progress = change['value']

    def _stream_data(self, chunk):
        """ Show progress """
        self._bytes += self._buffer.write(chunk)
        #self.progress = int(100*self._bytes/self._total_bytes)

    def _handle_response(self, response):
        self.status = u"Converting..."
        AndroidApplication.instance().force_update()
        try:
            #: Load buffer into json
            self._buffer.seek(3) # First 3 bytes are crap
            data = json.load(self._buffer)

            #: Create downloads folder
            downloads = os.path.dirname(self.path)
            if not os.path.exists(downloads):
                os.makedirs(downloads)

            #: Save in msgpack format
            with open(self.path, 'wb') as f:
                msgpack.dump(data, f)

            self.downloaded = True
            self.status = u"Done!"
        except Exception as e:
            self.status = u"{}".format(e)
        finally:
            self.downloading = False


class Bookmark(Atom):
    #: Name of it
    name = Unicode()

    #: Bible
    bible = ForwardInstance(lambda:Bible)

    #: Book
    book = Instance(Book)

    #: Chapter
    chapter = Instance(Chapter)

    #: Verse
    #verse = Instance(Verse)

    #: Save / load state
    state = Dict()

    def __init__(self, *args, **kwargs):
        super(Bookmark, self).__init__(*args, **kwargs)
        if kwargs.get('state') is None:
            #: If we're not loading from state
            self.state = {
                'bible': self.bible.version.key,
                'book': self.book.name,
                'chapter': self.chapter.number,
                #'verse': self.verse.number
            }

    def _default_name(self):
        return u"{} {}".format(self.book.name, self.chapter.number)

    def _default_bible(self):
        try:
            #: Prevent loading two bibles if it was bookmarked in a different bible
            bible = AppState.instance().bible
            if bible is not None:
                return bible
            return AppState.instance().get_bible(self.state['bible'])
        except KeyError:
            return None

    def _default_book(self):
        if not self.bible:
            return None
        try:
            return self.bible.get_book(self.state['book'])
        except KeyError:
            return None

    def _default_chapter(self):
        if not self.book:
            return None
        try:
            #: They're supposed to be in order
            return self.book.chapters[self.state['chapter']-1]
        except KeyError:
            return None


class Bible(Atom):
    #: Version
    version = Typed(Version)

    #: Bible is loading
    loading = Bool(True)

    #: Current
    current_book = Instance(Book)

    #: Current
    current_chapter = Instance(Chapter)

    #: Books
    books = List(Book)

    def get_book(self, name):
        for book in self.books:
            if book.name == name:
                return book

    def _observe_current_book(self, change):
        self.current_chapter = self.current_book.chapters[0]

    def _observe_version(self, change):
        self.loading = True
        try:
            path = self.version.path
            with open(path, 'rb') as f:
                data = msgpack.load(f)
            self.books = [Book(b) for b in data]
            self.current_book = self.books[0]

            # #: Test for expected chapter length because there seems to be issues here
            # expected = [
            #     ('genesis', 50),
            #     ('exodus', 40),
            #     ('leviticus', 27),
            #     ('numbers', 36),
            #     ('deuteronomy', 34),
            #     ('joshua', 24),
            #     ('judges', 21),
            #     ('ruth', 4),
            #     ('1-samuel', 31),
            #     ('2-samuel', 24),
            #     ('1-kings', 22),
            #     ('2-kings', 25),
            #     ('1-chronicles', 29),
            #     ('2-chronicles', 36),
            #     ('ezra', 10),
            #     ('nehemiah', 13),
            #     ('esther', 10),
            #     ('job', 42),
            #     ('psalms', 150),
            #     ('proverbs', 31),
            #     ('ecclesiastes', 12),
            #     ('song-of-solomon', 8),
            #     ('isaiah', 66),
            #     ('jeremiah', 52),
            #     ('lamentations', 5),
            #     ('ezekiel', 48),
            #     ('daniel', 12),
            #     ('hosea', 14),
            #     ('joel', 3),
            #     ('amos', 9),
            #     ('obadiah', 1),
            #     ('jonah', 4),
            #     ('micah', 7),
            #     ('nahum', 3),
            #     ('habakkuk', 3),
            #     ('zephaniah', 3),
            #     ('haggai', 2),
            #     ('zechariah', 14),
            #     ('malachi', 4),
            #     ('matthew', 28),
            #     ('mark', 16),
            #     ('luke', 24),
            #     ('john', 21),
            #     ('acts', 28),
            #     ('romans', 16),
            #     ('1-corinthians', 16),
            #     ('2-corinthians', 13),
            #     ('galatians', 6),
            #     ('ephesians', 6),
            #     ('philippians', 4),
            #     ('colossians', 4),
            #     ('1-thessalonians', 5),
            #     ('2-thessalonians', 3),
            #     ('1-timothy', 6),
            #     ('2-timothy', 4),
            #     ('titus', 3),
            #     ('philemon', 1),
            #     ('hebrews', 13),
            #     ('james', 5),
            #     ('1-peter', 5),
            #     ('2-peter', 3),
            #     ('1-john', 5),
            #     ('2-john', 1),
            #     ('3-john', 1),
            #     ('jude', 1),
            #     ('revelation', 22)
            # ]
            # for i,book in enumerate(self.books):
            #     #print("Book {} has {} chapters".format(book.name, len(book.chapters)))
            #     if len(book.chapters) != expected[i][1]:
            #         print("ERROR: Book {} version {} got {} expected {}".format(book.name,
            #                                                                     self.version.key,
            #                                                                     len(book.chapters),
            #                                                                     expected[i]))
        finally:
            self.loading = False

    def next_chapter(self):
        i = self.current_chapter.number-1
        i += 1 # Next chapter
        if i < len(self.current_book.chapters):
            #: Go to next chapter
            self.current_chapter = self.current_book.chapters[i]
            return
        #: Otherwise, go to start of next book
        i = self.books.index(self.current_book)
        i += 1
        if i < len(self.books):
            self.current_book = self.books[i]
        else:
            #: Back to the beginning
            self.current_book = self.books[0]


class Theme(Atom):
    """ Color themes"""
    toolbar_color = Unicode("#004981")
    toolbar_text = Unicode("#FFFFFF")
    background_color = Unicode('#EEEEEE')
    indicator_color = Unicode('#97c024')


class AppState(Atom):
    """ App state, need to load from file """

    _instance = None

    #: Screens
    screen = Enum("versions", "reader", "settings")

    #: Theme colors
    theme = Instance(Theme, ())

    #: List of bookmarks
    bookmarks = List(Bookmark)

    #: Bible versions
    bible_versions = Dict(basestring, Version, default={v.key: v for v in [
        Version(name="The Arabic Bible (SVD)", language="Arabic", key="ar_svd"),
        Version(name="Chinese Union Version (CUV)", language="Chinese", key="zh_cuv"),
        Version(name="New Chinese Version (NCV)", language="Chinese", key="zh_ncv"),
        Version(name="Schlachter", language="German", key="de_schlachter"),
        Version(name="Modern Greek", language="Greek", key="el_greek"),
        Version(name="Bible in Basic English (BBE)", language="English", key="en_bbe"),
        Version(name="King James Version (KJV)", language="English", key="en_kjv"),
        Version(name="Esperanto", language="Esperanto", key="eo_esperanto"),
        Version(name="Reina Valera (RVR)", language="Spanish", key="es_rvr"),
        Version(name="Finnish Bible", language="Finnish", key="fi_finnish"),
        Version(name=u"Pyhä Raamattu", language="Finnish", key="fi_pr"),
        Version(name=u"Le Bible de I'Épée", language="French", key="fr_apee"),
        Version(name=u"Korean Version", language="Korean", key="fr_apee"),
        Version(name=u"Almeida Revisada Imprensa Bíblica", language="Portuguese", key="pt_aa"),
        Version(name=u"Almeida Corrigida e Revisada Fiel", language="Portuguese", key="pt_acf"),
        Version(name=u"Nova Versão Internacional", language="Portuguese", key="pt_nvi"),
        Version(name=u"Versiunea Dumitru Cornilescu", language="Romanian", key="ro_cornilescu"),
        Version(name=u"Синодальный перевод", language="Russian", key="ru_synodal"),
        Version(name=u"Tiếng Việt", language="Vietnamese", key="vi_vietnamese"),
    ]})

    #: Saved state
    state = Dict()
    _save_delay = Int(100)
    _pending_saves = Int()

    #: Current bible
    bible = Instance(Bible)
    _bible_cache = Dict()  #: Cache loaded bibles

    #: Settings
    #: Text size
    text_size = Int(14)

    #: Order books on the left
    book_order = Enum('normal', 'alphabetical')

    #: Wake lock
    wake_lock = Bool()

    @classmethod
    def instance(cls):
        return cls._instance

    def __init__(self, *args, **kwargs):
        if self.instance() is not None:
            raise RuntimeError("AppState is a singleton, only one instance can exist!")
        super(AppState, self).__init__(*args, **kwargs)
        AppState._instance = self

    def get_bible(self, key):
        if not self._bible_cache.get('key', None):
            self._bible_cache[key] = Bible(version=self.bible_versions[key])
        return self._bible_cache[key]

    def _default_state(self):
        """ Load saved state if it exists"""
        try:
            #: Assets
            assets = os.path.dirname(os.path.dirname(__file__))
            with open(os.path.join(assets, 'state.msgp')) as f:
                state = msgpack.load(f)
            print("Loaded state: {}".format(state))
            return state
        except Exception as e:
            print("Failed to load state: {}".format(e))
            return {}

    def _save_state(self):
        """ Save state if it exists"""
        assets = os.path.dirname(os.path.dirname(__file__))
        try:
            with open(os.path.join(assets, 'state.msgp'), 'wb') as f:
                msgpack.dump(self.state, f)
        except Exception as e:
            print("Failed to save state: {}".format(e))

    def _default_screen(self):
        if self.bible is not None:
            return 'reader'
        return 'versions'

    def _default_bible(self):
        try:
            key = self.state['bible']
            return self.get_bible(key)
        except KeyError:
            return None

    def _observe_bible(self, change):
        if self.bible is None:
            if 'bible' in self.state:
                del self.state['bible']
        else:
            self.state['bible'] = self.bible.version.key

        #: When a bible is set, force an update
        AndroidApplication.instance().force_update()

    #: TODO: Some magic here would be nice
    def _default_text_size(self):
        return self.state.get('text_size', 14)

    def _observe_text_size(self, change):
        self.state['text_size'] = self.text_size

    def _default_book_order(self):
        return self.state.get('book_order', 'normal')

    def _observe_book_order(self, change):
        self.state['book_order'] = self.book_order

    def _default_bookmarks(self):
        return [Bookmark(state=state) for state in self.state.get('bookmarks', [])]

    def _observe_bookmarks(self, change):
        self.state['bookmarks'] = [b.state for b in self.bookmarks]

    def _default_wake_lock(self):
        return self.state.get('wake_lock', False)

    def _observe_wake_lock(self, change):
        AndroidApplication.instance().keep_screen_on = self.wake_lock
        self.state['wake_lock'] = self.wake_lock

    @observe('bookmarks', 'bible', 'text_size', 'book_order', 'wake_lock')
    def _queue_save(self, change):
        """ Schedule a save """
        self._pending_saves += 1
        AndroidApplication.instance().timed_call(self._save_delay, self._dequeue_save)

    def _dequeue_save(self):
        """ When pending saves complete, actually save """
        self._pending_saves -= 1
        if self._pending_saves == 0:
            self._save_state()
