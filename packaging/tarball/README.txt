WaveMaterial for Linux (portable .tar.gz)
=========================================

This archive is WaveMaterial with its own Python runtime and everything it needs from
Python. It is built on Arch Linux and comes with no compatibility guarantees: it runs if
your system has new enough versions of the libraries below. If it doesn't run, you can
run WaveMaterial from source instead (see the README in the repository).

Your system needs:
  - WebKitGTK 4.1 and GTK 3 (Arch: webkit2gtk-4.1; Debian: libwebkit2gtk-4.1-0)
  - GLib 2.80 or later with girepository-2.0
  - a Vulkan loader for fast mode on a graphics card (Arch: vulkan-icd-loader;
    Debian: libvulkan1); without one, it runs on the processor
  - GStreamer's "good" plugins for audio playback (Arch: gst-plugins-good;
    Debian: gstreamer1.0-plugins-good); without them, playback is turned off

Run it:
  ./bin/wavematerial

The first run asks before downloading the speech models (2.9 GB on disk). Your data goes
to the usual per-user folders (~/.local/share/wavematerial and others); nothing is written
inside this folder.

The models are in ~/.local/share/wavematerial/models unless you chose another folder (then
in a "WaveMaterial models" folder there). To remove them: Settings > Remove downloaded
models, or run
  ./bin/wavematerial models --remove
Deleting this folder removes the program but keeps the models and your transcripts.

Updating: when a new version is out, Settings > Self-update replaces this folder with it and
restarts WaveMaterial (the old folder is kept beside it, with .previous added to its name;
paths stay the same, so menu entries and links keep working). Manual update only saves the
new version to your Downloads folder.

Add it to your applications menu (optional): copy share/ into ~/.local/share/ and put
bin/wavematerial on your PATH, for example:
  cp -r share/. ~/.local/share/
  ln -s "$PWD/bin/wavematerial" ~/.local/bin/wavematerial

Licence: GPL-2.0-only WITH Universal-FOSS-exception-1.0 (see LICENSE.md). The licences of
everything bundled are listed in the app under Settings > Licences and credits. Source code,
including the exact sources of the bundled copyleft libraries, is attached to each release:
https://github.com/s7u512/wavematerial/releases
