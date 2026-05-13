"""Bloom-level shard store for ACML training samples.

Shard layout (one directory per shard):
  {bloom_level}--{index:04d}/
    data.jsonl          – append-only JSON lines, one record per line
    offsets.i32         – flat uint32-le pairs: [offset, length] × N  (8 bytes per entry)

Design invariants:
- Single shard never exceeds 4 GB (uint32 address space).
- Data is written *before* the offset entry; a crash between data flush and
  offset flush leaves one inaccessible trailing record, which is acceptable
  for bulk datasets.
- The offsets file size that is not a multiple of 8 is truncated to the
  last complete entry on open, so partial offset writes never corrupt the
  earlier index.
- The module avoids any heavy imports (torch / numpy / pandas) at module
  level so that ``--help`` and lightweight CLI entry-points stay fast.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Iterator, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHARD_MAX_BYTES: int = 4 * 1024**3  # 4 GiB hard limit (uint32 address space)
OFFSET_ENTRY_SIZE: int = 8           # uint32 offset + uint32 length
DATA_FILENAME: str = "data.jsonl"
OFFSETS_FILENAME: str = "offsets.i32"
SHARD_DIR_PATTERN: str = "{bloom_level}--{index:04d}"

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_shard_dir_name(dirname: str) -> Optional[tuple[str, int]]:
    """Parse 'analyze--0003' → ('analyze', 3), or None if not a shard dir."""
    if "--" not in dirname:
        return None
    bloom, idx_str = dirname.rsplit("--", 1)
    try:
        idx = int(idx_str)
    except ValueError:
        return None
    return bloom, idx


def _truncate_offsets_file(path: Path) -> None:
    """Truncate offsets.i32 to the last multiple of OFFSET_ENTRY_SIZE bytes."""
    if not path.exists():
        return
    size = path.stat().st_size
    valid = (size // OFFSET_ENTRY_SIZE) * OFFSET_ENTRY_SIZE
    if valid < size:
        # Partial final entry — truncate it away.
        with path.open("r+b") as fh:
            fh.truncate(valid)


# ---------------------------------------------------------------------------
# AcmlShardWriter
# ---------------------------------------------------------------------------


class AcmlShardWriter:
    """Append-only shard writer grouped by bloom_level.

    Usage::

        writer = AcmlShardWriter(Path("artifacts/shards"), bloom_level="analyze")
        for sample in samples:
            writer.append({"sample_id": sample.id, "acml": sample.acml, ...})
        writer.close()
    """

    def __init__(
        self,
        base_dir: str | Path,
        bloom_level: str,
        *,
        max_bytes: int = SHARD_MAX_BYTES,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.bloom_level = bloom_level
        self.max_bytes = max_bytes

        self._shard_index: int = 0
        self._data_fh: object = None   # BinaryIO, opened in append-binary
        self._offsets_fh: object = None
        self._current_data_size: int = 0
        self._sample_count_in_shard: int = 0
        self._total_sample_count: int = 0

        self._open_next_shard()

    # -- shard lifecycle --------------------------------------------------

    def _shard_dir(self) -> Path:
        return self.base_dir / SHARD_DIR_PATTERN.format(
            bloom_level=self.bloom_level, index=self._shard_index
        )

    def _open_next_shard(self) -> None:
        self._close_current()
        shard_dir = self._shard_dir()
        _ensure_dir(shard_dir)

        data_path = shard_dir / DATA_FILENAME
        offsets_path = shard_dir / OFFSETS_FILENAME

        existed = data_path.exists()
        self._data_fh = open(data_path, "ab")       # type: ignore[assignment]
        self._offsets_fh = open(offsets_path, "ab")  # type: ignore[assignment]

        if existed:
            self._current_data_size = data_path.stat().st_size
            _truncate_offsets_file(offsets_path)
            self._sample_count_in_shard = offsets_path.stat().st_size // OFFSET_ENTRY_SIZE
        else:
            self._current_data_size = 0
            self._sample_count_in_shard = 0

    def _close_current(self) -> None:
        if self._data_fh is not None:
            self._data_fh.close()
            self._data_fh = None
        if self._offsets_fh is not None:
            self._offsets_fh.close()
            self._offsets_fh = None

    def close(self) -> None:
        self._close_current()

    # -- append -----------------------------------------------------------

    def append(self, record: dict | str) -> None:
        """Append one record to the current shard.

        *record* may be a ``dict`` (serialised as a JSON line) or a raw
        ``str`` that already represents a complete JSON line (a trailing
        newline is added if missing).

        Shards roll over automatically when the next write would exceed
        *max_bytes*.
        """
        if isinstance(record, dict):
            line = json.dumps(record, ensure_ascii=False) + "\n"
        else:
            line = record if record.endswith("\n") else record + "\n"
        data = line.encode("utf-8")

        if self._current_data_size + len(data) > self.max_bytes:
            self._shard_index += 1
            self._open_next_shard()

        # 1. Write data — record the starting offset first.
        offset = self._data_fh.tell()       # type: ignore[union-attr]
        self._data_fh.write(data)           # type: ignore[union-attr]
        self._data_fh.flush()               # type: ignore[union-attr]

        # 2. Write offset entry  (little-endian uint32 pair).
        entry = struct.pack("<II", offset, len(data))
        self._offsets_fh.write(entry)       # type: ignore[union-attr]
        self._offsets_fh.flush()            # type: ignore[union-attr]

        self._current_data_size += len(data)
        self._sample_count_in_shard += 1
        self._total_sample_count += 1

    def append_batch(self, records: list[dict | str]) -> None:
        """Append multiple records (convenience wrapper)."""
        for rec in records:
            self.append(rec)

    # -- properties -------------------------------------------------------

    @property
    def sample_count(self) -> int:
        return self._total_sample_count

    @property
    def current_shard_sample_count(self) -> int:
        return self._sample_count_in_shard

    @property
    def current_shard_data_bytes(self) -> int:
        return self._current_data_size

    @property
    def current_shard_dir(self) -> Path:
        return self._shard_dir()

    @property
    def shard_index(self) -> int:
        return self._shard_index

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "AcmlShardWriter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# AcmlShardReader  (consumption side)
# ---------------------------------------------------------------------------


class AcmlShardReader:
    """Read a single shard directory.

    The offsets are available as a structured array for consumption as a 2-D
    matrix / struct-of-arrays.  Individual or batched reads are supported.

    Usage::

        reader = AcmlShardReader(Path("artifacts/shards/analyze--0000"))
        offsets = reader.offsets           # N×2 uint32 ndarray (requires numpy)
        offsets_list = reader.offsets_list  # list[(int, int)]  (pure Python)
        text_0 = reader[0]
        texts = reader.read_many([0, 5, 12])
    """

    def __init__(self, shard_dir: str | Path) -> None:
        self.shard_dir = Path(shard_dir)
        self.data_path = self.shard_dir / DATA_FILENAME
        self.offsets_path = self.shard_dir / OFFSETS_FILENAME

        if not self.data_path.exists():
            raise FileNotFoundError(f"data.jsonl not found in {self.shard_dir}")
        if not self.offsets_path.exists():
            raise FileNotFoundError(f"offsets.i32 not found in {self.shard_dir}")

        _truncate_offsets_file(self.offsets_path)
        self._data_fh = open(self.data_path, "rb")
        self._offsets_raw: bytes = self.offsets_path.read_bytes()

        self._n_entries = len(self._offsets_raw) // OFFSET_ENTRY_SIZE

    # -- properties -------------------------------------------------------

    @property
    def sample_count(self) -> int:
        return self._n_entries

    @property
    def offsets_list(self) -> list[tuple[int, int]]:
        """Return offsets as list[(offset, length)] — pure Python, no numpy."""
        result: list[tuple[int, int]] = []
        fmt = "<II"
        for i in range(self._n_entries):
            start = i * OFFSET_ENTRY_SIZE
            offset, length = struct.unpack_from(fmt, self._offsets_raw, start)
            result.append((offset, length))
        return result

    @property
    def offsets(self) -> "object":
        """Return offsets as a numpy structured array (N, 2) of uint32.

        Returns an array with dtype ``[('offset', '<u4'), ('length', '<u4')]``.
        To get a plain N×2 matrix: ``reader.offsets.view('<u4').reshape(-1, 2)``.
        """
        import numpy as np
        return np.frombuffer(
            self._offsets_raw,
            dtype=np.dtype([("offset", "<u4"), ("length", "<u4")]),
        )

    # -- read operations --------------------------------------------------

    def __len__(self) -> int:
        return self._n_entries

    def __getitem__(self, index: int) -> str:
        """Read a single sample by index, returning the raw JSON line."""
        if index < 0:
            index += self._n_entries
        if not (0 <= index < self._n_entries):
            raise IndexError(f"index {index} out of range [0, {self._n_entries})")
        fmt = "<II"
        offset, length = struct.unpack_from(fmt, self._offsets_raw, index * OFFSET_ENTRY_SIZE)
        self._data_fh.seek(offset)
        raw = self._data_fh.read(length)
        return raw.decode("utf-8")

    def read_record(self, index: int) -> dict:
        """Read and parse a sample as a JSON dict."""
        return json.loads(self[index])

    def read_many(self, indices: Sequence[int]) -> list[str]:
        """Read multiple samples.  Indices are read in-order for HDD locality."""
        # Sort for sequential-disk-access friendliness.
        sorted_indices = sorted(indices)
        result: list[Optional[str]] = [None] * len(indices)
        index_map = {idx: pos for pos, idx in enumerate(indices)}

        fmt = "<II"
        for idx in sorted_indices:
            offset, length = struct.unpack_from(fmt, self._offsets_raw, idx * OFFSET_ENTRY_SIZE)
            self._data_fh.seek(offset)
            raw = self._data_fh.read(length)
            result[index_map[idx]] = raw.decode("utf-8")

        return result  # type: ignore[return-value]

    def read_all(self) -> list[str]:
        """Read every sample in the shard (sequentially)."""
        return self.read_many(list(range(self._n_entries)))

    def iter_samples(self) -> Iterator[str]:
        """Sequential iterator over all samples (memory-efficient for huge shards)."""
        fmt = "<II"
        for i in range(self._n_entries):
            offset, length = struct.unpack_from(fmt, self._offsets_raw, i * OFFSET_ENTRY_SIZE)
            self._data_fh.seek(offset)
            yield self._data_fh.read(length).decode("utf-8")

    # -- context manager --------------------------------------------------

    def close(self) -> None:
        if self._data_fh is not None:
            self._data_fh.close()
            self._data_fh = None  # type: ignore[assignment]

    def __enter__(self) -> "AcmlShardReader":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def discover_shards(base_dir: str | Path) -> list[Path]:
    """Return shard directories under *base_dir*, sorted by (bloom_level, index)."""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    shards: list[tuple[str, int, Path]] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        parsed = _parse_shard_dir_name(entry.name)
        if parsed is None:
            continue
        bloom, idx = parsed
        # Quick sanity: the shard dir should contain data.jsonl
        if not (entry / DATA_FILENAME).exists():
            continue
        shards.append((bloom, idx, entry))
    shards.sort(key=lambda x: (x[0], x[1]))
    return [s[2] for s in shards]


def discover_shards_by_bloom(base_dir: str | Path) -> dict[str, list[Path]]:
    """Return {bloom_level: [shard_path, ...]} for all discovered shards."""
    result: dict[str, list[Path]] = {}
    for shard_path in discover_shards(base_dir):
        parsed = _parse_shard_dir_name(shard_path.name)
        if parsed is None:
            continue
        bloom = parsed[0]
        result.setdefault(bloom, []).append(shard_path)
    return result


def iter_shard_readers(base_dir: str | Path) -> Iterator[AcmlShardReader]:
    """Yield AcmlShardReader for every discovered shard, in stable order."""
    for shard_path in discover_shards(base_dir):
        yield AcmlShardReader(shard_path)


def shard_stats(base_dir: str | Path) -> list[dict]:
    """Return per-shard summary stats: bloom_level, sample_count, data_bytes."""
    stats: list[dict] = []
    for shard_path in discover_shards(base_dir):
        parsed = _parse_shard_dir_name(shard_path.name)
        if parsed is None:
            continue
        bloom, idx = parsed
        offsets_path = shard_path / OFFSETS_FILENAME
        data_path = shard_path / DATA_FILENAME
        n = offsets_path.stat().st_size // OFFSET_ENTRY_SIZE if offsets_path.exists() else 0
        d = data_path.stat().st_size if data_path.exists() else 0
        stats.append({
            "bloom_level": bloom,
            "shard_index": idx,
            "shard_dir": str(shard_path),
            "sample_count": n,
            "data_bytes": d,
            "offsets_bytes": n * OFFSET_ENTRY_SIZE,
        })
    return stats
