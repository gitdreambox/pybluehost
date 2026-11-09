"""Probe a PTS workspace via PTSControl COM: dump per-profile test-case counts,
how many are PICS-active, and (if possible) the PICS entry names.

Usage: python scripts/pts_probe_workspace.py <workspace.pqw6> [PROFILE ...]
"""
import sys

import pythoncom
import win32com.client


def main():
    ws = sys.argv[1]
    profiles = sys.argv[2:] or ["GAP", "GATT", "L2CAP", "SM"]

    pythoncom.CoInitialize()
    pts = win32com.client.Dispatch("ProfileTuningSuite_6.PTSControlServer")
    try:
        pts.SelectDevice("")
        import time
        time.sleep(4)
        pts.OpenWorkspace(ws)
        time.sleep(2)
        print("PTS version:", pts.GetPTSVersion())
        try:
            print("PTS addr:", pts.GetPTSBluetoothAddress())
        except Exception as e:
            print("PTS addr: <unavailable>", e)

        nproj = pts.GetProjectCount()
        print("project count:", nproj)
        for i in range(nproj):
            try:
                print("  project:", pts.GetProjectName(i))
            except Exception as e:
                print(f"  project[{i}]: <err {e}>")

        for prof in profiles:
            try:
                count = pts.GetTestCaseCount(prof)
            except Exception as e:
                print(f"[{prof}] GetTestCaseCount failed: {e}")
                continue
            active = []
            for j in range(count):
                name = pts.GetTestCaseName(prof, j)
                try:
                    if pts.IsActiveTestCase(prof, name):
                        active.append(name)
                except Exception:
                    pass
            print(f"[{prof}] total={count} active={len(active)}")
            for n in active[:40]:
                print("    active:", n)
            if len(active) > 40:
                print(f"    ... and {len(active)-40} more")
    finally:
        try:
            pts.ExitPTS()
        except Exception:
            pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
