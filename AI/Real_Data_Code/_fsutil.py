"""
Shared filesystem helper for the real-data pipeline.

WHY THIS EXISTS
---------------
The LaCie is exFAT, because it is shared between the Mac and the Windows
training machine. exFAT has no native extended attributes, so macOS stores
them in AppleDouble sidecar files named `._<original name>` -- and it creates
them whenever anything sets an xattr, including simply browsing the drive in
Finder or generating a Quick Look preview. They come back after any cleanup.

They are not images, and they break two things:

  1. `pathlib.Path.glob("*.png")` MATCHES them (unlike `glob.glob`, which
     skips leading-dot names the way a shell does). So a directory of 15
     frames silently becomes 19 "frames", four of which are unreadable.
  2. Tools that list a directory directly -- LabelMe among them -- try to open
     them and error out.

Every listing in this pipeline therefore goes through `list_files` rather than
calling `.glob` directly.
"""

from pathlib import Path


def is_hidden(p: Path) -> bool:
    """AppleDouble sidecars, .DS_Store, and any other dot-prefixed file."""
    return p.name.startswith(".")


def list_files(directory: Path, pattern: str = "*") -> list:
    """Sorted real files matching `pattern`, with hidden/sidecar files removed."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob(pattern) if not is_hidden(p))


def purge_sidecars(root: Path) -> int:
    """
    Delete AppleDouble sidecars and .DS_Store under `root`. Safe -- they hold
    only macOS metadata and are regenerated on demand. Returns the count.
    """
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and (p.name.startswith("._") or p.name == ".DS_Store"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Delete macOS sidecar files under a directory")
    ap.add_argument("root", type=Path)
    args = ap.parse_args()
    print(f"removed {purge_sidecars(args.root)} sidecar files under {args.root}")
