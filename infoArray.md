The following Markdown file defines the byte-to-object mapping for the `game_info` structure based on the provided hex dumps and human-readable data.

---

# DeuDeu2 Game Data Mapping Specification

## 1. Memory Layout (64-Byte Block)

The `gameInfo` structure is composed of a header containing IDs and Ranks, followed by four 32-bit (4-byte) integers stored in **Big Endian** format.

| Offset | Size | Field | Data Type | Description |
| --- | --- | --- | --- | --- |
| `0x00` | 1 | `char1_id` | `uint8` | Internal ID for Character 1 |
| `0x01` | 1 | `char1_rank` | `uint8` | Current Rank for Character 1 |
| `0x02` | 1 | `char2_id` | `uint8` | Internal ID for Character 2 |
| `0x03` | 1 | `char2_rank` | `uint8` | Current Rank for Character 2 |
| `0x04` | 4 | `char1_win` | `uint32_be` | Total Wins (Character 1) |
| `0x08` | 4 | `char1_lose` | `uint32_be` | Total Losses (Character 1) |
| `0x0C` | 4 | `char2_win` | `uint32_be` | Total Wins (Character 2) |
| `0x10` | 4 | `char2_lose` | `uint32_be` | Total Losses (Character 2) |
| `0x14` | 44 | `padding` | `byte[44]` | Reserved (Null/Zeroed) |

---

## 2. Character ID Reference Table

Extracted from the correlation between `gameInfo` hex values and human-readable labels.

| Hex ID | Character Name |
| --- | --- |
| `0x04` | Yoshimitsu |
| `0x08` | Christie |
| `0x09` | Jin |
| `0x0D` | Heihachi |
| `0x17` | Ganryu |
| `0x21` | Eddy |
| `0x22` | Bob |
| `0x26` | Lars |
| `0x2D` | Kunimitsu |

---

## 3. Practical Extraction Example (Record #4: DeuDeu2)

**Hex Segment:** `08 21 19 19 00 00 01 B4 00 00 00 4D 00 00 01 B4 00 00 00 4D`

1. **Header (`08 21 19 19`)**:
* `08` -> Christie
* `21` -> Eddy
* `19` -> Rank 25
* `19` -> Rank 25


2. **Wins/Losses**:
* `00 00 01 B4` -> **436** Wins
* `00 00 00 4D` -> **77** Losses



---

## 4. Implementation Logic (Python)

To parse these buffers programmatically, use the following `struct` format:

```python
import struct

# Format: > (Big Endian) 4B (4 unsigned chars) 4I (4 unsigned ints)
# Note: We only slice the first 20 bytes as the rest is padding.
data_format = ">4B4I"

def parse_game_info(data_bytes):
    header = data_bytes[:20]
    c1_id, c1_rank, c2_id, c2_rank, c1_w, c1_l, c2_w, c2_l = struct.unpack(data_format, header)
    return {
        "char1": {"id": c1_id, "rank": c1_rank, "win": c1_w, "lose": c1_l},
        "char2": {"id": c2_id, "rank": c2_rank, "win": c2_w, "lose": c2_l}
    }

```

---

Would you like me to create a script that parses all five of your provided hex samples into a clean CSV file?