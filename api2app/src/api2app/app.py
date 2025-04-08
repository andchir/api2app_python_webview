"""
Applications creator
"""

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW


class api2app(toga.App):
    def startup(self):
        """Construct and show the Toga application.

        Usually, you would add your application to a main content box.
        We then create a main window (with a name matching the app), and
        show the main window.
        """

        webview = toga.WebView(
            url='https://api2app.org',
            style=Pack(flex=1)
        )

        main_box = toga.Box(
            children=[webview],
            style=Pack(direction=COLUMN, flex=1)
        )

        self.main_window = toga.MainWindow(title=self.formal_name, size=(1024, 768))
        self.main_window.content = main_box
        self.main_window.show()


def main():
    return api2app()
