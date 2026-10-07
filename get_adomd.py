"""Backup way to get ADOMD.NET: downloads it from NuGet (Microsoft's package site)
into the 'adomd' folder here. Use this if the Microsoft installer (.msi) isn't
available or you can't install software on your PC. No admin rights needed.

Run:  python get_adomd.py
"""
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "adomd"

# ADOMD.NET plus the sign-in libraries it references
PACKAGES = [
    "Microsoft.AnalysisServices.AdomdClient",
    "Microsoft.Identity.Client",
    "Microsoft.IdentityModel.Abstractions",
]
# .NET Framework builds, newest first (pythonnet uses .NET Framework on Windows)
FRAMEWORKS = ["net472", "net471", "net47", "net462", "net461", "net46", "net45", "netstandard2.0"]


def download(package: str) -> bytes:
    url = f"https://www.nuget.org/api/v2/package/{package}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def extract_dlls(nupkg: bytes, dest: Path) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(nupkg)) as z:
        names = z.namelist()
        for fw in FRAMEWORKS:
            prefix = f"lib/{fw}/"
            dlls = [n for n in names if n.lower().startswith(prefix.lower()) and n.lower().endswith(".dll")
                    and "/" not in n[len(prefix):]]
            if dlls:
                copied = []
                for n in dlls:
                    out = dest / Path(n).name
                    with z.open(n) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f)
                    copied.append(f"{Path(n).name} ({fw})")
                return copied
    return []


def main() -> int:
    TARGET.mkdir(exist_ok=True)
    for pkg in PACKAGES:
        print(f"Downloading {pkg} ...")
        try:
            files = extract_dlls(download(pkg), TARGET)
        except Exception as exc:
            print(f"  Failed: {exc}\n  Check your internet connection or proxy, then try again.")
            return 1
        if not files:
            print("  No .NET Framework files found in this package.")
            return 1
        for f in files:
            print(f"  + {f}")

    if (TARGET / "Microsoft.AnalysisServices.AdomdClient.dll").exists():
        print(f"\nDone. ADOMD.NET is in {TARGET}. Next: python build_schema.py")
        return 0
    print("\nSomething went wrong: the ADOMD.NET file is missing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
