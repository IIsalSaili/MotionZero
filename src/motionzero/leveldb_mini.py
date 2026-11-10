"""Lecteur minimal de base LevelDB (format utilisé par le « Local Storage » de Discord / Chrome).

Lecture seule, sur une COPIE des fichiers (Discord les verrouille). On ne cherche qu'une clé précise :
toutes les autres entrées (dont le jeton de connexion) sont ignorées sans être décodées ni gardées.

Format : fichiers .log (journal d'écritures, non compressé) et .ldb (tables triées, blocs éventuellement
compressés en Snappy). Chaque entrée porte un numéro de séquence : la plus récente gagne.
"""
import os
import shutil
import struct
import tempfile

import cramjam


def _varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


# --- tables .ldb -------------------------------------------------------------------------------------
def _block(data, offset, size):
    raw = data[offset:offset + size]
    kind = data[offset + size]
    if kind == 1:
        raw = bytes(cramjam.snappy.decompress_raw(raw))
    return raw


def _block_entries(block):
    n_restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    end = len(block) - 4 - 4 * n_restarts
    pos, key = 0, b""
    while pos < end:
        shared, pos = _varint(block, pos)
        unshared, pos = _varint(block, pos)
        vlen, pos = _varint(block, pos)
        key = key[:shared] + block[pos:pos + unshared]
        pos += unshared
        yield key, block[pos:pos + vlen]
        pos += vlen


def _table(path, want):
    data = open(path, "rb").read()
    footer = data[-48:]
    _, p = _varint(footer, 0)            # metaindex (ignoré)
    _, p = _varint(footer, p)
    idx_off, p = _varint(footer, p)
    idx_size, p = _varint(footer, p)
    for _, handle in _block_entries(_block(data, idx_off, idx_size)):
        off, q = _varint(handle, 0)
        size, _ = _varint(handle, q)
        for ikey, value in _block_entries(_block(data, off, size)):
            user_key, tag = ikey[:-8], struct.unpack("<Q", ikey[-8:])[0]
            if want(user_key):
                yield user_key, tag >> 8, (tag & 0xFF) == 1, value


# --- journal .log ------------------------------------------------------------------------------------
def _log(path, want):
    data = open(path, "rb").read()
    record, pos = b"", 0
    while pos + 7 <= len(data):
        block_left = 32768 - pos % 32768
        if block_left < 7:
            pos += block_left
            continue
        length, kind = struct.unpack_from("<HB", data, pos + 4)
        chunk = data[pos + 7:pos + 7 + length]
        pos += 7 + length
        if kind in (1, 2):               # FULL / FIRST
            record = chunk
        elif kind in (3, 4):             # MIDDLE / LAST
            record += chunk
        else:
            continue
        if kind in (1, 4):
            yield from _batch(record, want)


def _batch(rec, want):
    if len(rec) < 12:
        return
    seq, count = struct.unpack_from("<QI", rec, 0)
    pos = 12
    for i in range(count):
        if pos >= len(rec):
            return
        kind = rec[pos]
        pos += 1
        klen, pos = _varint(rec, pos)
        key = rec[pos:pos + klen]
        pos += klen
        value = b""
        if kind == 1:
            vlen, pos = _varint(rec, pos)
            value = rec[pos:pos + vlen]
            pos += vlen
        if want(key):
            yield key, seq + i, kind == 1, value


def latest_value(db_dir, want):
    """Valeur la plus récente d'une clé qui satisfait want(clé), ou None (absente / supprimée)."""
    tmp = tempfile.mkdtemp(prefix="mz_ldb_")
    try:
        best = None
        for name in os.listdir(db_dir):
            if not (name.endswith(".ldb") or name.endswith(".log")):
                continue
            dst = os.path.join(tmp, name)
            shutil.copyfile(os.path.join(db_dir, name), dst)
            reader = _table if name.endswith(".ldb") else _log
            try:
                for _key, seq, alive, value in reader(dst, want):
                    if best is None or seq > best[0]:
                        best = (seq, alive, value)
            except (IndexError, struct.error, ValueError):
                continue                 # fichier en cours d'écriture : on l'ignore
        return best[2] if best and best[1] else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
