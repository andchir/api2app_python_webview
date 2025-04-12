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

Create icons:
~~~
https://makeappicon.com/
~~~

Replace icons in:
~~~
api2app/build/api2app/android/gradle/app/src/main/res
~~~

Build for Android:
~~~
briefcase run android
briefcase create android
briefcase build android
briefcase package android
~~~

Build for Windows:
~~~
briefcase run windows
briefcase create windows
briefcase package windows
briefcase package windows -p msi
briefcase package windows -p zip
~~~
