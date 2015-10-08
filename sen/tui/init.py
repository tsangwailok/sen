import logging

from sen.tui.buffer import LogsBuffer, MainListBuffer, InspectBuffer, HelpBuffer
from sen.tui.constants import PALLETE
from sen.docker_backend import DockerBackend

import urwid


logger = logging.getLogger(__name__)


class UI(urwid.MainLoop):
    def __init__(self):
        self.d = DockerBackend()

        # root widget
        self.mainframe = urwid.Frame(urwid.SolidFill())
        self.status_bar = None
        self.notif_bar = None
        root_widget = urwid.AttrMap(self.mainframe, "root")
        self.main_list_buffer = None  # singleton

        screen = urwid.raw_display.Screen()
        screen.set_terminal_properties(256)
        screen.register_palette(PALLETE)

        super().__init__(root_widget, screen=screen)
        self.handle_mouse = False
        self.current_buffer = None
        self.buffers = []

    def refresh(self):
        self.draw_screen()

    def _set_main_widget(self, widget, redraw):
        """
        add provided widget to widget list and display it

        :param widget:
        :return:
        """
        self.mainframe.set_body(widget)
        bottom = []
        if self.notif_bar:
            bottom.append(self.notif_bar)
        self.status_bar = self.build_statusbar()
        bottom.append(self.status_bar)
        self.mainframe.set_footer(urwid.Pile(bottom))
        if redraw:
            logger.debug("redraw main widget")
            self.refresh()

    def display_buffer(self, buffer, redraw=True):
        """
        display provided buffer

        :param buffer: Buffer
        :return:
        """
        self.current_buffer = buffer
        self._set_main_widget(buffer.widget, redraw=redraw)

    def add_and_display_buffer(self, buffer, redraw=True):
        """
        add provided buffer to buffer list and display it

        :param buffer:
        :return:
        """
        if buffer not in self.buffers:
            logger.debug("adding new buffer {!r}".format(buffer))
            self.buffers.append(buffer)
        self.display_buffer(buffer, redraw=redraw)

    def pick_and_display_buffer(self, i):
        """
        pick i-th buffer from list and display it

        :param i: int
        :return: None
        """
        if len(self.buffers) == 1:
            # we don't need to display anything
            # listing is already displayed
            return
        else:
            try:
                self.display_buffer(self.buffers[i])
            except IndexError:
                # i > len
                self.display_buffer(self.buffers[0])

    @property
    def current_buffer_index(self):
        return self.buffers.index(self.current_buffer)

    def remove_current_buffer(self):
        # don't allow removing main_list
        if isinstance(self.current_buffer, MainListBuffer):
            logger.warning("you can't remove main list widget")
            return
        self.buffers.remove(self.current_buffer)
        self.current_buffer.destroy()
        # FIXME: we should display last displayed widget here
        self.display_buffer(self.buffers[0], True)

    def unhandled_input(self, key):
        logger.debug("got %r", key)
        if key in ('q', 'Q'):
            raise urwid.ExitMainLoop()
        elif key == "N":
            self.pick_and_display_buffer(self.current_buffer_index - 1)
        elif key == "n":
            self.pick_and_display_buffer(self.current_buffer_index + 1)
        elif key == "x":
            self.remove_current_buffer()
        elif key in ["h", "?"]:
            self.display_help()

    def run(self):
        self.main_list_buffer = MainListBuffer(self.d, self)
        self.add_and_display_buffer(self.main_list_buffer, redraw=False)
        super().run()

    def display_logs(self, docker_container):
        self.add_and_display_buffer(LogsBuffer(docker_container, self))

    def display_and_follow_logs(self, docker_container):
        self.add_and_display_buffer(LogsBuffer(docker_container, self, follow=True))

    def inspect(self, docker_object):
        self.add_and_display_buffer(InspectBuffer(docker_object))

    def refresh_main_buffer(self):
        assert self.main_list_buffer is not None
        self.main_list_buffer.refresh()
        self.display_buffer(self.main_list_buffer)

    def display_help(self):
        self.add_and_display_buffer(HelpBuffer())

    def build_statusbar(self):
        """construct and return statusbar widget"""
        lefttxt = ("Images: {images}, Containers: {all_containers},"
                   " Running: {running_containers}, {last_command}() -> {last_command_took:f} ms".
        format(
            last_command=self.d.last_command,  # these gotta be first
            last_command_took=self.d.last_command_took,
            images=len(self.d.images),
            all_containers=len(self.d.containers),
            running_containers=len(self.d.sorted_containers(sort_by_time=False, stopped=False)),
        ))
        t = []
        for idx, buffer in enumerate(self.buffers):
            fmt = "[{}] {}"
            if buffer == self.current_buffer:
                fmt += "*"
            t.append(fmt.format(idx, buffer.display_name))
        righttxt = " ".join(t)

        footerleft = urwid.Text(lefttxt, align='left')

        footerright = urwid.Text(righttxt, align='right', wrap="clip")
        columns = urwid.Columns([
            footerleft,
            footerright])
        return urwid.AttrMap(columns, "default")

    def notify(self, message, level="info"):
        """
        :param level: str, {info, error}

        opens notification popup.
        """
        msgs = [urwid.AttrMap(urwid.Text(message), "notif_{}".format(level))]

        # stack errors, don't overwrite them
        if not self.notif_bar:
            self.notif_bar = urwid.Pile(msgs)
        else:
            newpile = self.notif_bar.widget_list + msgs
            self.notif_bar = urwid.Pile(newpile)

        self.refresh_main_buffer()

        def clear(*args):
            newpile = self.notif_bar.widget_list
            for l in msgs:
                if l in newpile:
                    newpile.remove(l)
            if newpile:
                self.notif_bar = urwid.Pile(newpile)
            else:
                self.notif_bar = None
            self.refresh_main_buffer()

        self.set_alarm_in(10, clear)
