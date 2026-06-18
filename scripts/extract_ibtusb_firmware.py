#!/usr/bin/env python3
"""Extract Intel Bluetooth firmware blobs embedded in ibtusb*.sys files.

The Intel Windows Bluetooth drivers used by the PTS packages keep firmware as
static PE data, not as Win32 resources.  The table layout observed in the
analyzed drivers is a sequence of 64-bit pairs:

    <firmware_blob_va>, <ascii_name_va>

where the name is an ASCII string such as ``sfi_BLAZARU_A0_FMP_C0`` or
``bseq_BLAZARU_A0_WHP_A0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path


NAME_RE = re.compile(rb"\b(?:sfi|bseq)_[A-Za-z0-9_]+(?=\x00)")
SFI_MAGIC = b"\x06\x00\x00\x00\xa1\x00\x00\x00"


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int

    def contains_rva(self, rva: int) -> bool:
        size = max(self.virtual_size, self.raw_size)
        return self.virtual_address <= rva < self.virtual_address + size

    def rva_to_offset(self, rva: int) -> int:
        return self.raw_offset + (rva - self.virtual_address)

    def contains_offset(self, offset: int) -> bool:
        return self.raw_offset <= offset < self.raw_offset + self.raw_size

    def offset_to_rva(self, offset: int) -> int:
        return self.virtual_address + (offset - self.raw_offset)


@dataclass(frozen=True)
class PeImage:
    data: bytes
    image_base: int
    sections: tuple[Section, ...]

    def va_to_offset(self, va: int) -> int | None:
        rva = va - self.image_base
        for section in self.sections:
            if section.contains_rva(rva):
                offset = section.rva_to_offset(rva)
                if 0 <= offset < len(self.data):
                    return offset
        return None

    def offset_to_va(self, offset: int) -> int | None:
        for section in self.sections:
            if section.contains_offset(offset):
                return self.image_base + section.offset_to_rva(offset)
        return None


@dataclass(frozen=True)
class FirmwareEntry:
    name: str
    name_off: int
    name_va: int
    entry_off: int
    blob_va: int
    blob_off: int
    size: int
    sha256: str
    file: str
    head: str


def parse_pe(data: bytes) -> PeImage:
    if data[:2] != b"MZ":
        raise ValueError("not a PE image: missing MZ header")

    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off : pe_off + 4] != b"PE\x00\x00":
        raise ValueError("not a PE image: missing PE signature")

    coff_off = pe_off + 4
    section_count = struct.unpack_from("<H", data, coff_off + 2)[0]
    optional_size = struct.unpack_from("<H", data, coff_off + 16)[0]
    optional_off = coff_off + 20
    magic = struct.unpack_from("<H", data, optional_off)[0]
    if magic == 0x20B:
        image_base = struct.unpack_from("<Q", data, optional_off + 24)[0]
    elif magic == 0x10B:
        image_base = struct.unpack_from("<I", data, optional_off + 28)[0]
    else:
        raise ValueError(f"unsupported PE optional header magic: 0x{magic:x}")

    sections: list[Section] = []
    section_off = optional_off + optional_size
    for index in range(section_count):
        off = section_off + index * 40
        raw_name = data[off : off + 8].split(b"\x00", 1)[0]
        name = raw_name.decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, off + 8
        )
        sections.append(
            Section(
                name=name,
                virtual_address=virtual_address,
                virtual_size=virtual_size,
                raw_offset=raw_offset,
                raw_size=raw_size,
            )
        )

    return PeImage(data=data, image_base=image_base, sections=tuple(sections))


def iter_names(data: bytes) -> list[tuple[str, int]]:
    names: list[tuple[str, int]] = []
    for match in NAME_RE.finditer(data):
        names.append((match.group(0).decode("ascii"), match.start()))
    return names


def find_entry_for_name(pe: PeImage, name_off: int) -> tuple[int, int] | None:
    name_va = pe.offset_to_va(name_off)
    if name_va is None:
        return None

    needle = struct.pack("<Q", name_va)
    start = 0
    while True:
        found = pe.data.find(needle, start)
        if found < 0:
            return None
        entry_off = found - 8
        if entry_off >= 0:
            blob_va = struct.unpack_from("<Q", pe.data, entry_off)[0]
            blob_off = pe.va_to_offset(blob_va)
            if blob_off is not None and is_plausible_blob(pe.data, blob_off):
                return entry_off, blob_va
        start = found + 1


def is_plausible_blob(data: bytes, offset: int) -> bool:
    return data.startswith(SFI_MAGIC, offset) or data[offset : offset + 2] == b"\x01\x8b"


def parse_bseq_size(data: bytes, start: int, limit: int) -> int:
    pos = start
    last_good = start
    while pos < limit:
        packet_type = data[pos]
        if packet_type == 0x00:
            break
        if packet_type == 0x01:
            if pos + 4 > limit:
                break
            packet_len = 4 + data[pos + 3]
        elif packet_type == 0x02:
            if pos + 3 > limit:
                break
            packet_len = 3 + data[pos + 2]
        else:
            break
        if packet_len <= 0 or pos + packet_len > limit:
            break
        pos += packet_len
        last_good = pos
    if last_good == start:
        raise ValueError(f"could not parse BSEQ at file offset 0x{start:x}")
    return last_good - start


def parse_sfi_size(data: bytes, start: int, next_blob_off: int | None) -> int:
    if not data.startswith(SFI_MAGIC, start):
        raise ValueError(f"missing SFI magic at file offset 0x{start:x}")
    if start + 28 > len(data):
        raise ValueError(f"truncated SFI header at file offset 0x{start:x}")

    # Intel SFI images observed here store the main image length at offset 0x18
    # as a DWORD count, with a 320-byte signed header before payload data.
    declared = struct.unpack_from("<I", data, start + 0x18)[0] * 4 + 320
    if declared <= 320 or start + declared > len(data):
        raise ValueError(f"invalid SFI declared length at file offset 0x{start:x}")

    if next_blob_off is not None:
        span = next_blob_off - start
        if span <= 0:
            raise ValueError(f"invalid next blob offset after 0x{start:x}")
        # The table entries are 8- or 16-byte aligned.  If the next blob starts
        # immediately after the declared image plus padding, include the padding
        # because it is part of the embedded object extent in this SYS image.
        if declared <= span <= declared + 16:
            return span
        if span < declared:
            return span
    aligned = (declared + 15) & ~15
    if aligned > declared and start + aligned <= len(data):
        padding = data[start + declared : start + aligned]
        if all(byte == 0 for byte in padding):
            return aligned
    return declared


def extract_entries(sys_path: Path) -> list[FirmwareEntry]:
    data = sys_path.read_bytes()
    pe = parse_pe(data)

    pending: list[dict[str, int | str]] = []
    seen_entry_offsets: set[int] = set()
    for name, name_off in iter_names(data):
        found = find_entry_for_name(pe, name_off)
        if found is None:
            continue
        entry_off, blob_va = found
        if entry_off in seen_entry_offsets:
            continue
        blob_off = pe.va_to_offset(blob_va)
        name_va = pe.offset_to_va(name_off)
        if blob_off is None or name_va is None:
            continue
        seen_entry_offsets.add(entry_off)
        pending.append(
            {
                "name": name,
                "name_off": name_off,
                "name_va": name_va,
                "entry_off": entry_off,
                "blob_va": blob_va,
                "blob_off": blob_off,
            }
        )

    pending.sort(key=lambda item: int(item["blob_off"]))
    blob_offsets = [int(item["blob_off"]) for item in pending]
    entries: list[FirmwareEntry] = []
    for index, item in enumerate(pending):
        name = str(item["name"])
        blob_off = int(item["blob_off"])
        next_blob_off = blob_offsets[index + 1] if index + 1 < len(blob_offsets) else None
        if name.startswith("sfi_"):
            size = parse_sfi_size(data, blob_off, next_blob_off)
            extension = "sfi"
        elif name.startswith("bseq_"):
            if next_blob_off is None:
                next_blob_off = min(len(data), blob_off + 4096)
            size = parse_bseq_size(data, blob_off, next_blob_off)
            extension = "bseq"
        else:
            continue

        blob = data[blob_off : blob_off + size]
        entries.append(
            FirmwareEntry(
                name=name,
                name_off=int(item["name_off"]),
                name_va=int(item["name_va"]),
                entry_off=int(item["entry_off"]),
                blob_va=int(item["blob_va"]),
                blob_off=blob_off,
                size=size,
                sha256=hashlib.sha256(blob).hexdigest().upper(),
                file=f"{name}.{extension}",
                head=blob[:16].hex(),
            )
        )

    return entries


def write_outputs(sys_path: Path, output_dir: Path, entries: list[FirmwareEntry]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = sys_path.read_bytes()
    manifest = []
    for entry in entries:
        (output_dir / entry.file).write_bytes(data[entry.blob_off : entry.blob_off + entry.size])
        manifest.append(entry.__dict__)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def default_output_dir(sys_path: Path, base_output_dir: Path) -> Path:
    stem = sys_path.stem
    parent = sys_path.parent
    component = parent.parent.name if parent.name.lower() == "x64" else parent.name
    package = parent
    for ancestor in sys_path.parents:
        if ancestor.name.upper().endswith("PTS") or "_PTS_" in ancestor.name.upper():
            package = ancestor
            break
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{package.name}_{component}_{stem}").strip("_")
    return base_output_dir / safe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sys", nargs="+", type=Path, help="ibtusb*.sys file(s) to analyze")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("extracted_firmware_from_sys"),
        help="base output directory",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="print JSON manifest without writing firmware files",
    )
    args = parser.parse_args()

    all_results: dict[str, list[dict[str, object]]] = {}
    for sys_path in args.sys:
        sys_path = sys_path.resolve()
        entries = extract_entries(sys_path)
        if not entries:
            raise SystemExit(f"no embedded firmware table found in {sys_path}")
        all_results[str(sys_path)] = [entry.__dict__ for entry in entries]
        if not args.manifest_only:
            out_dir = default_output_dir(sys_path, args.output_dir)
            write_outputs(sys_path, out_dir, entries)
            print(f"{sys_path}: extracted {len(entries)} blobs -> {out_dir}")

    if args.manifest_only:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
