#!/usr/bin/env python3
"""Build official Stockfish source with the Android NDK; retain matching source."""
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'android'/'build'/'stockfish-source'
SOURCE_TAG='sf_19'


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def main():
    ndk=Path(os.environ['ANDROID_NDK_HOME'])
    toolchain=ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'
    if not toolchain.exists(): raise SystemExit('This build helper expects the official Linux NDK toolchain on the CI runner.')
    WORK.parent.mkdir(parents=True,exist_ok=True)
    if not WORK.exists():
        run(['git','clone','--depth','1','--branch',SOURCE_TAG,'https://github.com/official-stockfish/Stockfish.git',str(WORK)])
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORK,text=True).strip()
    source=WORK/'src'
    run(['make','net'],cwd=source)
    for abi,architecture,compiler in [('arm64-v8a','armv8','aarch64-linux-android26-clang++'),('x86_64','x86-64','x86_64-linux-android26-clang++')]:
        run(['make','clean'],cwd=source)
        run(['make','-j2','build',f'ARCH={architecture}','COMP=ndk',f'COMPCXX={toolchain/compiler}',
             'EXTRALDFLAGS=-Wl,-z,max-page-size=16384'],cwd=source,
            env={**os.environ,'PATH':str(toolchain)+os.pathsep+os.environ['PATH']})
        target=ROOT/'android/app/src/main/jniLibs'/abi/'libstockfish.so'
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'stockfish',target)
        run([str(toolchain/'llvm-readelf'),'-h',str(target)])
    run(['make','clean'],cwd=source)
    package=ROOT/'apk';package.mkdir(exist_ok=True)
    with zipfile.ZipFile(package/'Stockfish-Corresponding-Source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in WORK.rglob('*'):
            relative=file.relative_to(WORK)
            if file.is_file() and '.git' not in relative.parts:
                archive.write(file,Path('Stockfish')/relative)
        archive.write(Path(__file__),'build_android_stockfish.py')
        archive.writestr('BUILD.txt',f'Official Stockfish {SOURCE_TAG}\nCommit: {revision}\nAndroid NDK: {ndk.name}\nAndroid API 26; armv8 and x86-64; COMP=ndk; max-page-size=16384.\nThe matching NNUE files are included in src/. Run the supplied build helper with the NDK installed.\n')
    license_file=WORK/'Copying.txt'
    if not license_file.exists(): raise SystemExit('Stockfish license missing.')
    assets=ROOT/'android/app/src/main/assets/licenses';assets.mkdir(parents=True,exist_ok=True)
    shutil.copy2(license_file,assets/'Stockfish-GPL-3.txt')
    (assets/'Stockfish-source.txt').write_text(f'Stockfish {SOURCE_TAG}, commit {revision}. Matching source, NNUE networks and build helper accompany the APK as Stockfish-Corresponding-Source.zip. https://github.com/official-stockfish/Stockfish/tree/{revision}\n')


if __name__=='__main__': main()
