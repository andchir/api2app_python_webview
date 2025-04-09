"""
api2app - Applications creator
"""

import toga
from toga.style import Pack
from toga.style.pack import COLUMN
from toga.constants import CENTER
import requests

SITE_URL = 'https://api2app.org'


def check_internet_connection():
    try:
        response = requests.get('http://connectivitycheck.gstatic.com/generate_204', timeout=5)
        return response.status_code == 204
    except requests.exceptions.RequestException:
        return False


class api2app(toga.App):
    def startup(self):
        toga.Font.register('bootstrap-icons', 'resources/bootstrap-icons/fonts/bootstrap-icons.ttf')

        if not check_internet_connection():
            icon_label = toga.Label(
                '\uf61c',
                style=Pack(font_family='bootstrap-icons', font_size=60, padding=10, text_align='center')
            )

            text_label = toga.Label(
                'Проверьте Ваше Интернет-соединение',
                style=Pack(font_size=16, padding=10, text_align='center')
            )
            main_box = toga.Box(children=[icon_label, text_label], style=Pack(direction=COLUMN, alignment=CENTER, padding=20))

        else:
            webview = toga.WebView(
                url=SITE_URL,
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
