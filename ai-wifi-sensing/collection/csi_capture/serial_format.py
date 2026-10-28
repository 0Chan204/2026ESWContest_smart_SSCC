"""Accept AI_WIFI's six columns and Espressif's classic CSI_DATA CSV."""
import csv
import io
import json
import math
import re

HEADER = ["host_timestamp", "local_timestamp", "data", "rssi", "mac", "first_word", "len"]
MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$", re.I)


def parse_line(line):
    if not isinstance(line, str):
        return None
    try:
        row = next(csv.reader([line.strip()]))
        if len(row) == 6:
            timestamp, data, rssi, mac, first, length = row
        elif len(row) == 25 and row[0] == "CSI_DATA":
            timestamp, data, rssi, mac, first, length = row[18], row[24], row[3], row[2], row[23], row[22]
        else:
            return None
        values = json.loads(data)
        if (not isinstance(values, list) or not 128 <= len(values) <= 4096
                or any(type(x) is not int or not -128 <= x <= 127 for x in values)
                or int(length) != len(values) or not 0 <= int(timestamp) < 2**32
                or int(first) not in (0, 1) or not math.isfinite(float(rssi))
                or not MAC.fullmatch(mac.strip())):
            return None
        valid_indices = [*range(38, 64), *range(1, 27)]
        if not any(values[2 * (2 if int(first) and k == 1 else k)]
                   or values[2 * (2 if int(first) and k == 1 else k) + 1] for k in valid_indices):
            return None
        return [int(timestamp), json.dumps(values, separators=(",", ":")), float(rssi),
                mac.strip().lower(), int(first), len(values)]
    except (ValueError, TypeError, csv.Error, StopIteration):
        return None


def normalize_capture(raw: bytes, *, trim_each=0, sample_count=None):
    source = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if source.fieldnames != ["host_timestamp", "raw_line"]:
        raise ValueError("Expected host_timestamp,raw_line capture header")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(HEADER)
    count = skipped = 0
    packets = []
    for row in source:
        try:
            host = float(row["host_timestamp"])
            packet = parse_line(row["raw_line"])
            if packet is None or not math.isfinite(host):
                skipped += 1
                continue
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
        packets.append([f"{host:.6f}", *packet])
        count += 1
    if sample_count is None:
        kept = packets
    else:
        # Only the first N+2*trim valid packets belong to the requested capture.
        packets = packets[:sample_count + 2 * trim_each]
        kept = packets[trim_each:len(packets) - trim_each] if len(packets) > 2 * trim_each else []
    writer.writerows(kept)
    quality = {"accepted_rows": count, "skipped_rows": skipped}
    if sample_count is not None:
        quality.update(retained_rows=len(kept), trimmed_head=min(trim_each, len(packets)),
                       trimmed_tail=min(trim_each, max(0, len(packets) - trim_each)))
    return output.getvalue().encode(), quality
