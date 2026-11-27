# PyInstaller bundles Python, Qt, yt-dlp and Playwright. FFmpeg remains an explicit
# external dependency so users can select an appropriate licensed build.
from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path
root = Path(SPECPATH).parent

datas=[(str(root/"build/build-info.json"), "."),(str(root/"videobot/assets"), "videobot/assets"),(str(root/"build"/"third-party-notices"), "THIRD-PARTY-NOTICES"), (str(root/"LICENSE"), ".")]; binaries=[]; hiddenimports=[]
for package in ('yt_dlp','yt_dlp_ejs','playwright','faster_whisper','ctranslate2'):
    d,b,h=collect_all(package); datas+=d; binaries+=b; hiddenimports+=h
for package in ('videobot-desktop','yt-dlp','yt-dlp-ejs','playwright','PySide6-Essentials','PySide6-Addons','shiboken6','faster-whisper','ctranslate2','av','tokenizers','huggingface-hub'):
    datas+=copy_metadata(package)
a=Analysis([str(root/'run.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hiddenimports,
           excludes=['pytest','ruff','pip_audit','PyQt6','PyQt5','PySide2'],noarchive=False)
# Discovery uses headless Chromium only. Exclude the unused full Chrome app;
# rewriting its nested signed frameworks during collection breaks macOS bundles.
def needed(entry):
    return not any('/.local-browsers/chromium-' in str(value).replace('\\','/') for value in entry[:2])
a.binaries = [entry for entry in a.binaries if needed(entry)]
a.datas = [entry for entry in a.datas if needed(entry)]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='VideoBot',console=False)
coll=COLLECT(exe,a.binaries,a.datas,name='VideoBot')
import sys
if sys.platform=='darwin':
    app=BUNDLE(coll,name='VideoBot.app',icon=str(root/'build/VideoBot.icns'),bundle_identifier='com.shadowfetchstudio.videobot',
               info_plist={'CFBundleShortVersionString':'2.3.0','NSHighResolutionCapable':True})
