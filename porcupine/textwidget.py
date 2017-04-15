"""The big text widget in the middle of the editor."""

import functools
import re
import tkinter as tk
import tkinter.font as tkfont

from porcupine import config, utils

# the editing section is all about the big text widget
config.add_key('editing', 'font', [None, 10])
config.add_key('editing', 'undo', True)
config.add_key('editing', 'indent', 4)    # TODO: tabs? (whyyy :( lol)


@config.validator('editing', 'font')
def _check_font(font):
    print(font)
    family, size = font
    if family is None:
        # this recurses a bit, but it's not too bad
        init_font()
        return True
    if not 0 < size < 1000:
        return False
    return family in tkfont.families()


def init_font():
    """Make sure that the font family is set.

    This should be called after the root window is created.
    """
    print(config.get('editing', 'font'))
    family, size = config.get('editing', 'font')
    if family is None:
        default_font = tkfont.Font(font='TkFixedFont')
        config.set('editing', 'font', [default_font['family'], size])


def _spacecount(string):
    """Count how many spaces the string starts with.

    >>> _spacecount('  123')
    2
    >>> _spacecount('  \n')
    2
    """
    result = 0
    for char in string:
        if char == '\n' or not char.isspace():
            break
        result += 1
    return result


# this can be used for implementing other themed things too, e.g. the
# line number plugin
class ThemedText(tk.Text):

    def __init__(self, *args, use_current_theme=True, **kwargs):
        super().__init__(*args, **kwargs)
        init_font()
        config.connect('editing', 'font', self._on_font_changed)

        self._use_current_theme = use_current_theme
        if use_current_theme:
            config.connect('general', 'color_theme', self.set_theme_name)

    # tkinter seems to call this automatically
    def destroy(self):
        config.disconnect('editing', 'font', self._on_font_changed)
        if self._use_current_theme:
            config.disconnect('general', 'color_theme', self.set_theme_name)
        super().destroy()

    def _on_font_changed(self, font):
        family, size = font
        self['font'] = (family, size, '')

    def set_theme_name(self, name):
        theme = config.color_themes[name]
        self['fg'] = theme['foreground']
        self['bg'] = theme['background']
        self['insertbackground'] = theme['foreground']  # cursor color
        self['selectforeground'] = theme['selectforeground']
        self['selectbackground'] = theme['selectbackground']


# TODO: turn indent/strip stuff into plugin(s)?
class MainText(ThemedText):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # These will contain callback functions that are called with no
        # arguments after the text in the textview is updated.
        self.on_cursor_move = []
        self.on_modified = []
        self.on_complete_previous = []
        self.on_complete_next = []
        self._cursorpos = '1.0'

        def cursor_move(event):
            self.after_idle(self._do_cursor_move)

        partial = functools.partial     # avoid long lines
        self.bind('<<Modified>>', self._do_modified)
        self.bind('<Button-1>', cursor_move)
        self.bind('<Key>', cursor_move)
        self.bind('<Control-a>', self._on_ctrl_a)
        self.bind('<BackSpace>', partial(self._on_delete, False))
        self.bind('<Control-BackSpace>', partial(self._on_delete, True))
        self.bind('<Control-Delete>', partial(self._on_delete, True))
        self.bind('<Return>', self._on_return)
        self.bind('<parenright>', self._on_closing_brace)
        self.bind('<bracketright>', self._on_closing_brace)
        self.bind('<braceright>', self._on_closing_brace)
        self.bind('<Control-z>', self.undo)
        self.bind('<Control-y>', self.redo)
        self.bind('<Control-x>', self.cut)
        self.bind('<Control-c>', self.copy)
        self.bind('<Control-v>', self.paste)
        self.bind('<Control-a>', self.select_all)
        self.bind('<Tab>', lambda event: self._on_tab(False))
        if self.tk.call('tk', 'windowingsystem') == 'x11':
            # even though the event keysym says Left, holding down right
            # shift and pressing tab also runs this event... 0_o
            self.bind('<ISO_Left_Tab>', lambda event: self._on_tab(True))
        else:
            self.bind('<Shift-Tab>', lambda event: self._on_tab(True))

        utils.bind_mouse_wheel(self, self._on_wheel, prefixes='Control-')
        self.bind('<Control-plus>', self._zoom_in)
        self.bind('<Control-minus>', self._zoom_out)
        self.bind('<Control-Key-0>', self._zoom_reset)

        config.connect('editing', 'undo', self._set_undo)

    def destroy(self):
        config.disconnect('editing', 'undo', self._set_undo)
        super().destroy()

    def _set_undo(self, undo):
        self['undo'] = undo

    # ThemedText.__init__ ran init_font() so we're sure that the family
    # has been set
    def _zoom_in(self, event=None):
        # can't mutate the config value :(
        family, size = config.get('editing', 'font')

        # 1.2 is a good multiplier here because round(3 * 1.2) is 4 and
        # round(4 / 1.2) is 3
        size = round(size * 1.2)
        if size < 1000:
            config.set('editing', 'font', [family, size])

    def _zoom_out(self, event=None):
        family, size = config.get('editing', 'font')
        size = round(size / 1.2)
        if size >= 3:
            config.set('editing', 'font', [family, size])

    def _zoom_reset(self, event):
        family, size = config.get('editing', 'font')
        config.set('editing', 'font', [family, 10])

    def _on_wheel(self, direction):
        if direction == 'up':
            self._zoom_in()
        else:
            self._zoom_out()

    def _do_modified(self, event):
        # this runs recursively if we don't unbind
        self.unbind('<<Modified>>')
        self.edit_modified(False)
        self.bind('<<Modified>>', self._do_modified)
        for callback in self.on_modified:
            callback()

    def _do_cursor_move(self):
        cursorpos = self.index('insert')
        if cursorpos != self._cursorpos:
            self._cursorpos = cursorpos
            for callback in self.on_cursor_move:
                callback()

    def _on_delete(self, control_down, event):
        """This runs when the user presses backspace or delete."""
        if not self.tag_ranges('sel'):
            # nothing is selected, we can do non-default stuff
            if event.keysym == 'BackSpace':
                lineno = int(self.index('insert').split('.')[0])
                before_cursor = self.get('%d.0' % lineno, 'insert')
                if before_cursor and before_cursor.isspace():
                    self.dedent(lineno)
                    return 'break'

                if control_down:
                    # delete previous word
                    old_cursor_pos = self.index('insert')
                    self.event_generate('<<PrevWord>>')
                    self.delete('insert', old_cursor_pos)
                    return 'break'

            if event.keysym == 'Delete' and control_down:
                # delete next word
                old_cursor_pos = self.index('insert')
                self.event_generate('<<NextWord>>')
                self.delete(old_cursor_pos, 'insert')

        self.after_idle(self._do_cursor_move)
        return None

    def _on_ctrl_a(self, event):
        self.select_all()
        return 'break'     # don't run _on_key or move cursor

    def _on_return(self, event):
        """Schedule automatic indent and whitespace stripping."""
        # the whitespace must be stripped after autoindenting,
        # see _autoindent()
        self.after_idle(self._autoindent)
        self.after_idle(self._rstrip_prev_line)
        self.after_idle(self._do_cursor_move)

    def _on_closing_brace(self, event):
        """Dedent automatically."""
        lineno = int(self.index('insert').split('.')[0])
        beforethis = self.get('%d.0' % lineno, 'insert')
        if beforethis.isspace():
            self.dedent(lineno)
        self.after_idle(self._do_cursor_move)

    def _on_tab(self, shifted):
        """Indent, dedent or autocomplete."""
        if shifted:
            complete_callbacks = self.on_complete_previous
            indenter = self.dedent
        else:
            complete_callbacks = self.on_complete_next
            indenter = self.indent

        try:
            sel_start, sel_end = map(str, self.tag_ranges('sel'))
        except ValueError:
            # no text is selected
            lineno = int(self.index('insert').split('.')[0])
            before_cursor = self.get('%d.0' % lineno, 'insert')
            if before_cursor.isspace() or not before_cursor:
                indenter(lineno)
            else:
                for callback in complete_callbacks:
                    callback()
        else:
            # something selected, indent/dedent block
            first_lineno = int(sel_start.split('.')[0])
            last_lineno = int(sel_end.split('.')[0])
            for lineno in range(first_lineno, last_lineno+1):
                indenter(lineno)
                self.rstrip(lineno)

        # indenting and autocomplete: don't insert the default tab
        # dedenting: don't move focus out of this widget
        return 'break'

    def indent(self, lineno):
        """Indent by one level.

        Return the resulting number of spaces in the beginning of
        the line.
        """
        line = self.get('%d.0' % lineno, '%d.0+1l' % lineno)
        spaces = _spacecount(line)
        indent = config.get('editing', 'indent')

        # make the indent consistent, for example, add 1 space if indent
        # is 4 and there are 7 spaces
        spaces2add = indent - (spaces % indent)
        self.insert('%d.0' % lineno, ' ' * spaces2add)
        self._do_cursor_move()
        return spaces + spaces2add

    def dedent(self, lineno):
        """Unindent by one level if possible.

        Return the resulting number of spaces in the beginning of
        the line.
        """
        line = self.get('%d.0' % lineno, '%d.0+1l' % lineno)
        spaces = _spacecount(line)
        if spaces == 0:
            return 0

        indent = config.get('editing', 'indent')
        howmany2del = spaces % indent
        if howmany2del == 0:
            howmany2del = indent
        self.delete('%d.0' % lineno, '%d.%d' % (lineno, howmany2del))
        self._do_cursor_move()
        return spaces - howmany2del

    def _autoindent(self):
        """Indent or dedent the current line automatically if needed."""
        lineno = int(self.index('insert').split('.')[0])
        prevline = self.get('%d.0-1l' % lineno, '%d.0' % lineno)
        self.insert('insert', _spacecount(prevline) * ' ')

        # we can't strip trailing whitespace before this because then
        # pressing enter twice would get rid of all indentation
        prevline = prevline.strip()
        if prevline.endswith((':', '(', '[', '{')):
            # start of a new block
            self.indent(lineno)
        elif (prevline in {'return', 'break', 'pass', 'continue'}
              or prevline.startswith('return ')):
            # must be end of a block
            self.dedent(lineno)

    def rstrip(self, lineno):
        """Strip trailing whitespace at the end of a line."""
        line_end = '%d.0+1l-1c' % lineno
        line = self.get('%d.0' % lineno, line_end)
        spaces = _spacecount(line[::-1])
        if spaces == 0:
            return

        deleting_start = '{}-{}c'.format(line_end, spaces)
        self.delete(deleting_start, line_end)

    def _rstrip_prev_line(self):
        """Strip whitespace after end of previous line."""
        lineno = int(self.index('insert').split('.')[0])
        self.rstrip(lineno-1)

    def undo(self, event=None):
        try:
            self.edit_undo()
        except tk.TclError:     # nothing to undo
            return
        self._do_cursor_move()
        return 'break'

    def redo(self, event=None):
        try:
            self.edit_redo()
        except tk.TclError:     # nothing to redo
            return
        self._do_cursor_move()
        return 'break'

    def cut(self, event=None):
        self.event_generate('<<Cut>>')
        self._do_cursor_move()
        return 'break'

    def copy(self, event=None):
        self.event_generate('<<Copy>>')
        self._do_cursor_move()
        return 'break'

    def paste(self, event=None):
        self.event_generate('<<Paste>>')

        # Without this, pasting while some text is selected is annoying
        # because the selected text doesn't go away :(
        try:
            sel_start, sel_end = self.tag_ranges('sel')
        except ValueError:
            # nothing selected
            pass
        else:
            self.delete(sel_start, sel_end)

        self._do_cursor_move()
        return 'break'

    def select_all(self, event=None):
        self.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    # these methods may move the cursor, there are other methods too but
    # they aren't currently used
    def insert(self, *args, **kwargs):
        super().insert(*args, **kwargs)
        self._do_cursor_move()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._do_cursor_move()

    def iter_chunks(self):
        """Iterate over the content as 100-line chunks.

        This method does not break lines in the middle.
        """
        start = 1
        while True:
            end = start + 100
            if self.index('%d.0' % end) == self.index('end'):
                yield self.get('%d.0' % start, 'end-1c')
                break
            yield self.get('%d.0' % start, '%d.0' % end)
            start = end
