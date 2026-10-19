"""Small X11 helper for the controls in the upstream prebuilt Unity demos."""
import subprocess
import time

from Xlib import X, XK, display, protocol, error
from Xlib.ext import xtest


class UnityUI:
    def __init__(self, pid, timeout=40, display_name=None, window_size=(1600, 900)):
        self.display = display.Display(display_name)
        self.root = self.display.screen().root
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            prop = self.root.get_full_property(self.display.intern_atom('_NET_CLIENT_LIST'), X.AnyPropertyType)
            windows = [w.id for w in self.root.query_tree().children] if prop is None else prop.value
            for wid in windows:
                window = self.display.create_resource_object('window', int(wid))
                process = window.get_full_property(self.display.intern_atom('_NET_WM_PID'), X.AnyPropertyType)
                if process is not None and int(process.value[0]) == pid:
                    geometry = window.get_geometry()
                    if geometry.width > 400:
                        self.window = window
                        self.window.configure(x=0, y=0, width=window_size[0], height=window_size[1])
                        self.display.sync()
                        time.sleep(0.5)
                        geometry = window.get_geometry()
                        self.width, self.height = geometry.width, geometry.height
                        self.focus()
                        return
            time.sleep(0.2)
        raise RuntimeError('Unity window did not appear; check DISPLAY and unity.log')

    def focus(self):
        active = self.display.intern_atom('_NET_ACTIVE_WINDOW')
        if self.root.get_full_property(self.display.intern_atom('_NET_SUPPORTING_WM_CHECK'), X.AnyPropertyType):
            event = protocol.event.ClientMessage(window=self.window, client_type=active,
                                                data=(32, [1, X.CurrentTime, 0, 0, 0]))
            self.root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            self.display.flush()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                prop = self.root.get_full_property(active, X.AnyPropertyType)
                if prop is not None and int(prop.value[0]) == self.window.id:
                    break
                time.sleep(0.05)
        self.window.configure(stack_mode=X.Above)
        self.window.set_input_focus(X.RevertToParent, X.CurrentTime)
        self.display.sync()
        time.sleep(0.15)

    @staticmethod
    def focus_host_window(display_name, title):
        """Activate Xephyr on the desktop as well as Unity inside its server."""
        host = display.Display(display_name)
        try:
            root = host.screen().root
            clients = root.get_full_property(host.intern_atom('_NET_CLIENT_LIST'), X.AnyPropertyType)
            windows = clients.value if clients is not None else [w.id for w in root.query_tree().children]
            for wid in windows:
                window = host.create_resource_object('window', int(wid))
                if window.get_wm_name() != title:
                    continue
                event = protocol.event.ClientMessage(window=window,
                    client_type=host.intern_atom('_NET_ACTIVE_WINDOW'),
                    data=(32, [2, X.CurrentTime, 0, 0, 0]))
                root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                window.configure(stack_mode=X.Above)
                window.set_input_focus(X.RevertToParent, X.CurrentTime)
                host.sync()
                return
            raise RuntimeError(f'没有找到 FPS 桌面窗口：{title}')
        finally:
            host.close()

    def move(self, x, y):
        self.focus()
        origin = self.root.translate_coords(self.window, 0, 0)
        xtest.fake_input(self.display, X.MotionNotify,
                         x=origin.x + round(x * self.width / 1280),
                         y=origin.y + round(y * self.height / 720))
        self.display.sync()
        time.sleep(0.05)

    def click(self, x, y):
        self.move(x, y)
        xtest.fake_input(self.display, X.ButtonPress, 1)
        self.display.sync()
        time.sleep(0.08)
        xtest.fake_input(self.display, X.ButtonRelease, 1)
        self.display.sync()
        time.sleep(0.15)

    def key(self, key, down):
        code = self.display.keysym_to_keycode(XK.string_to_keysym(key))
        if not code:
            raise ValueError(f'Unknown key: {key}')
        xtest.fake_input(self.display, X.KeyPress if down else X.KeyRelease, code)
        self.display.sync()

    def tap(self, key):
        self.key(key, True)
        time.sleep(0.04)
        self.key(key, False)

    def text(self, x, y, text):
        self.click(x, y)
        self.key('Control_L', True)
        self.tap('a')
        self.key('Control_L', False)
        for char in str(text):
            symbol = ord(char)
            code = self.display.keysym_to_keycode(symbol)
            shift = self.display.keycode_to_keysym(code, 0) != symbol
            if shift:
                self.key('Shift_L', True)
            xtest.fake_input(self.display, X.KeyPress, code)
            xtest.fake_input(self.display, X.KeyRelease, code)
            if shift:
                self.key('Shift_L', False)
            self.display.sync()
            time.sleep(0.006)
        self.tap('Return')

    def connect(self):
        # ROS-TCP-Connector's debug panel uses a fixed 300x105 pixel rectangle.
        self.click(150 * 1280 / self.width, 65 * 720 / self.height)

    def screenshot(self, path):
        self.focus()
        subprocess.run(['import', '-display', self.display.get_display_name(),
                        '-window', hex(self.window.id), str(path)], check=True, timeout=10)

    def close(self):
        try:
            self.display.close()
        except (error.ConnectionClosedError, OSError):
            pass
