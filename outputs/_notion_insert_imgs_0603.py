# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import get_children, insert_after, image_block, upload_image

PAGE = "374fda35-a098-81be-8169-df66dc48ef45"  # 🌅 2026.6.3 早间日报
IMGS = [
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_1_fed.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_2_iran.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_3_longs.png",
]

# find the 基本面 paragraph block
ch = get_children(PAGE)
after = None
for b in ch:
    if b["type"] == "paragraph":
        txt = "".join(x.get("plain_text", "") for x in b["paragraph"]["rich_text"])
        if txt.startswith("基本面"):
            after = b["id"]; break
print("基本面 block:", after)
assert after, "未找到 基本面 段落"

# dedup: if an image already directly follows, abort
blocks = [image_block(upload_image(p)) for p in IMGS]
insert_after(PAGE, after, blocks)
print("INSERTED", len(blocks), "images after 基本面")
