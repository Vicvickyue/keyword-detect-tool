# Third-party notices

This application uses the unmodified 7-Zip command-line program by Igor Pavlov
(`7z.exe` and `7z.dll`). 7-Zip is licensed primarily under the GNU LGPL, with
BSD-licensed components and unRAR restrictions as described in the bundled
`_internal/vendor/7zip/License.txt`. Source code and versioned distributions:
https://www.7-zip.org/ and https://github.com/ip7z/7zip . The bundled binaries
are external to this application's source and are not committed to this repository.

The interface uses Qt for Python / PySide6 Essentials and Shiboken6 under their
applicable LGPL/GPL/commercial terms. This distribution uses the open-source
LGPL modules dynamically; corresponding notices are included under `licenses/`.
Users may replace the compatible Qt/PySide6 libraries in `_internal` and may
debug modifications to those libraries. Sources: https://code.qt.io/cgit/pyside/pyside-setup.git/
and https://code.qt.io/ . Qt source archives: https://download.qt.io/official_releases/ .

Other runtime dependencies: openpyxl (MIT), et-xmlfile (MIT), python-calamine
(MIT), ReportLab (BSD), charset-normalizer (MIT), pyahocorasick (BSD), Pillow
(MIT-CMU). The package includes their installed license notices and metadata.
Python is distributed under the PSF License; its license is copied from the
build interpreter into `licenses/PYTHON_LICENSE.txt`. PyInstaller is GPL with the bootloader exception.

The report uses an installed Windows Chinese font (Microsoft YaHei, SimSun,
or SimHei) and embeds a font subset in the PDF. Windows font files are not
redistributed in this application package.
