"""Line numbers for tkinter's Text widget.

This doesn't handle scrolling in any way. See multiscrollbar.py.
"""

import tkinter as tk

from porcupine import config, plugins
from porcupine.textwidget import ThemedText

# TODO: more configuration options
config.add_key('editing', 'linenumbers', True)


class ScrollManager:
    """Scroll two text widgets with one scrollbar."""

    def __init__(self, scrollbar, main_widget, other_widgets):
        self._scrollbar = scrollbar
        self._main_widget = main_widget
        self._widgets = [main_widget] + other_widgets

    def _yview(self, *args):
        for widget in self._widgets:
            widget.yview(*args)

    def _set(self, beginning, end):
        self._scrollbar.set(beginning, end)
        self._yview('moveto', beginning)

    def enable(self):
        self._scrollbar['command'] = self._yview
        for widget in self._widgets:
            widget['yscrollcommand'] = self._set

    def disable(self):
        # all scrolled widgets except the default widget should be
        # hidden when this runs
        self._scrollbar['command'] = self._main_widget.yview
        self._main_widget['yscrollcommand'] = self._scrollbar.set


class LineNumbers(ThemedText):

    def __init__(self, parent, textwidget, **kwargs):
        super().__init__(parent, width=6, height=1, **kwargs)
        self.textwidget = textwidget
        self.insert('1.0', " 1")    # this is always there
        self['state'] = 'disabled'  # must be after the insert
        self._linecount = 1

    def do_update(self):
        """This should be ran when the line count changes."""
        linecount = int(self.textwidget.index('end-1c').split('.')[0])
        if linecount > self._linecount:
            # add more linenumbers
            self['state'] = 'normal'
            for i in range(self._linecount + 1, linecount + 1):
                self.insert('end-1c', '\n %d' % i)
            self['state'] = 'disabled'
        if linecount < self._linecount:
            # delete the linenumbers we don't need
            self['state'] = 'normal'
            self.delete('%d.0+1l-1c' % linecount, 'end-1c')
            self['state'] = 'disabled'
        self._linecount = linecount


def filetab_hook(filetab):
    linenumbers = LineNumbers(filetab.mainframe, filetab.textwidget)
    scrollmgr = ScrollManager(
        filetab.scrollbar, filetab.textwidget, [linenumbers])

    def show_or_hide(showing):
        if showing:
            linenumbers.pack(side='left', fill='y')
            scrollmgr.enable()
        else:
            linenumbers.pack_forget()
            scrollmgr.disable()

    filetab.textwidget.on_modified.append(linenumbers.do_update)
    with config.connect('editing', 'linenumbers', show_or_hide):
        yield
    filetab.textwidget.on_modified.remove(linenumbers.do_update)


plugins.add_plugin("Line Numbers", filetab_hook=filetab_hook)


if __name__ == '__main__':
    import porcupine.settings

    root = tk.Tk()
    porcupine.settings.load()

    theme = config.color_themes[config.get('general', 'color_theme')]
    text = tk.Text(root, fg=theme['foreground'], bg=theme['background'])
    linenumbers = LineNumbers(root, text)
    linenumbers.pack(side='left', fill='y')
    text.pack(side='left', fill='both', expand=True)

    def on_lineno_change(event):
        text.after_idle(linenumbers.do_update)

    # this isn't perfect but this is good enough for this test
    text.bind('<Return>', on_lineno_change)
    text.bind('<BackSpace>', on_lineno_change)
    text.bind('<Delete>', on_lineno_change)

    root.mainloop()
