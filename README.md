# pyg
simple python clash gui

import os
import sys
import json
import yaml
import winreg
import shutil
import urllib.request
import threading
import zipfile
import subprocess
import tkinter as tk
# pyinstaller
python -m PyInstaller -D -w --strip --noupx `
  --exclude-module unittest `
  --exclude-module test `
  --exclude-module pydoc `
  --exclude-module distutils `
  --exclude-module xml `
  --exclude-module tkinter.test `
  --collect-all yaml `
 main.py
