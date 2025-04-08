# api2app WebView app

Install:
https://toga.readthedocs.io/en/latest/reference/platforms/linux.html#prerequisites
~~~
sudo apt install build-essential pkg-config libgirepository-2.0-dev libcairo2-dev gir1.2-gtk-3.0 libcanberra-gtk3-module
~~~

~~~
python3.12 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
~~~

Run in dev mode:
~~~
briefcase dev
~~~

Build for Android:
~~~
briefcase create android
~~~

Run the app on a virtual device:
~~~
briefcase run android
~~~
