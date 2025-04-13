"""
api2app - Applications creator
"""

import toga
from toga.style import Pack
from toga.style.pack import COLUMN
from toga.constants import CENTER
import requests

SITE_URL = 'https://api2app.org'


class api2app(toga.App):
    def startup(self):
        toga.Font.register('bootstrap-icons', 'resources/bootstrap-icons/fonts/bootstrap-icons.ttf')

        self.main_window = toga.MainWindow(title=self.formal_name, size=(1024, 768))

        if not self.check_internet_connection():
            icon_label = toga.Label(
                '\uf61c',
                style=Pack(font_family='bootstrap-icons', font_size=60, padding=10, text_align='center')
            )
            text_label = toga.Label(
                'Проверьте Интернет-соединение',
                style=Pack(font_size=14, padding=10, text_align='center')
            )
            refresh_button = toga.Button(
                'Обновить',
                on_press=self.update_webview,
                style=Pack(padding=(10, 20))
            )
            main_box = toga.Box(children=[icon_label, text_label, refresh_button], style=Pack(direction=COLUMN, alignment=CENTER, padding=20))
            self.main_window.content = main_box

        else:
            self.update_webview()
        self.main_window.show()

    def update_webview(self, widget=None):
        if not self.check_internet_connection():
            return
        webview = toga.WebView(
            url=SITE_URL,
            style=Pack(flex=1)
        )
        main_box = toga.Box(
            children=[webview],
            style=Pack(direction=COLUMN, flex=1)
        )
        self.main_window.content = main_box

    def check_internet_connection(self):
        try:
            response = requests.get('http://connectivitycheck.gstatic.com/generate_204', timeout=5)
            return response.status_code == 204
        except requests.exceptions.RequestException:
            return False


def main():
    return api2app()
