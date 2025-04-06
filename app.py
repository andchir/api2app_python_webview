import toga
from toga.style import Pack
from toga.style.pack import COLUMN


class BeeWareBrowser(toga.App):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.main_window = None

    def startup(self):
        self.main_window = toga.MainWindow(title=self.formal_name, size=(1024, 768))

        webview = toga.WebView(
            url='https://api2app.org',
            style=Pack(flex=1)
        )

        box = toga.Box(
            children=[webview],
            style=Pack(direction=COLUMN, flex=1)
        )

        self.main_window.content = box
        self.main_window.show()


def main():
    return BeeWareBrowser(
        formal_name='api2app',
        app_id='org.beeware.browser',
    )


if __name__ == '__main__':
    app = main()
    app.main_loop()
