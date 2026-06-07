# -*- coding: utf-8 -*-
# 把 3 张快讯卡补插到已建的 6/6 晚间页基本面块后（图片上传 SSL 抖断后续插·不重建页）
import sys, time
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import get_children, insert_after, image_block, upload_image

PID = "377fda35-a098-8131-943f-f81670f0df43"

ch = get_children(PID)
n_img = sum(1 for b in ch if b["type"] == "image")
print("existing images:", n_img)
after = None
for b in ch:
    if b["type"] == "heading_3":
        txt = "".join(x.get("plain_text", "") for x in b["heading_3"]["rich_text"])
        if txt.startswith("基本面"):
            after = b["id"]; break
print("after 基本面:", after)

imgs = [
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_1_macro.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_2_geo.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_3_oversold.png",
]

if n_img >= 3:
    print("already has 3 imgs, skip")
else:
    fids = []
    for p in imgs:
        for attempt in range(5):
            try:
                fids.append(upload_image(p)); break
            except Exception as e:
                print("retry upload", attempt, str(e)[:50]); time.sleep(2)
        else:
            raise SystemExit("upload failed " + p)
    # 一次性按序插入（保持 macro->geo->oversold 顺序）
    for attempt in range(5):
        try:
            insert_after(PID, after, [image_block(f) for f in fids]); break
        except Exception as e:
            print("retry insert", attempt, str(e)[:50]); time.sleep(2)
    else:
        raise SystemExit("insert failed")
    print("DONE inserted", len(fids))
