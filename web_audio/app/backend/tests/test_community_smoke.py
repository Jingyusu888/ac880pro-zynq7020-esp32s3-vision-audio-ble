"""社区层冒烟测试：不吃 pytest，直接 python 跑。

    cd D:/petlink2
    ./.venv/Scripts/python.exe -m app.backend.tests.test_community_smoke

用临时目录里的独立 sqlite，绝不碰 app/data/petlink_web.sqlite 里已有数据。
覆盖：注册登录 → 建宠物 → 发帖 → 信息流 → 点赞幂等 → 评论 → 权限 → 识别分享 → 删除。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def _bootstrap(tmp_root: Path):
    """把 config 的路径指向临时目录，再导入 app（导入顺序不能反）。"""
    from app.backend import config as cfg

    cfg.DATA_DIR = tmp_root / "data"
    cfg.UPLOADS_DIR = cfg.DATA_DIR / "uploads"
    cfg.EXPORTS_DIR = cfg.DATA_DIR / "exports"
    cfg.DATABASE_PATH = cfg.DATA_DIR / "petlink_web.sqlite"

    import app.backend.database as database
    database.DATA_DIR = cfg.DATA_DIR
    database.UPLOADS_DIR = cfg.UPLOADS_DIR
    database.EXPORTS_DIR = cfg.EXPORTS_DIR
    database.DATABASE_PATH = cfg.DATABASE_PATH

    from app.backend.main import app
    database.init_database()   # TestClient 不用 context manager，startup 事件不会自动跑
    return app


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="petlink_community_"))
    app = _bootstrap(tmp)

    from fastapi.testclient import TestClient
    client = TestClient(app)
    ok = 0
    failed = []

    def check(name, cond, extra=""):
        nonlocal ok
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {extra}")

    print(f"临时库：{tmp}")

    # 1. 注册并登录（注册即建会话）
    r = client.post("/api/auth/register", json={"username": "smoke_a", "display_name": "甲", "password": "pw123456"})
    check("注册", r.status_code == 200, r.text[:200])
    me = client.get("/api/auth/me").json()
    user_a = me.get("user", {}).get("user_id", "") or me.get("user_id", "")
    check("拿到当前用户", bool(user_a), json.dumps(me, ensure_ascii=False)[:200])

    # 2. 建宠物
    r = client.post("/api/pets", json={"name": "煤球", "species": "cat", "breed": "狸花", "age": "2", "bio": ""})
    check("建宠物", r.status_code == 200, r.text[:200])
    pet_id = r.json().get("pet_id", "")
    check("宠物有 id", bool(pet_id))

    # 3. 发帖
    r = client.post("/api/community/posts", json={"content": "第一条动态", "pet_id": pet_id})
    check("发帖", r.status_code == 200, r.text[:200])
    post = r.json()
    post_id = post.get("post_id", "")
    check("帖子带作者名", post.get("author_name") == "甲", json.dumps(post, ensure_ascii=False)[:200])
    check("帖子带宠物名", post.get("pet_name") == "煤球")
    check("初始点赞数 0", post.get("likes_count") == 0)

    # 4. 空内容被拒
    r = client.post("/api/community/posts", json={"content": "   "})
    check("空内容 400", r.status_code == 400, r.text[:120])

    # 5. 信息流
    r = client.get("/api/community/feed")
    feed = r.json()
    check("信息流 200", r.status_code == 200)
    check("信息流包含刚发的帖", any(i["post_id"] == post_id for i in feed.get("items", [])))

    # 6. 点赞幂等
    r1 = client.post(f"/api/community/posts/{post_id}/like")
    r2 = client.post(f"/api/community/posts/{post_id}/like")
    check("点赞 200", r1.status_code == 200, r1.text[:120])
    check("重复点赞不叠加", r2.json().get("likes_count") == 1, r2.text[:120])
    r = client.get(f"/api/community/posts/{post_id}")
    check("liked_by_me=True", r.json().get("liked_by_me") in (1, True))

    # 7. 取消点赞
    r = client.delete(f"/api/community/posts/{post_id}/like")
    check("取消点赞后归零", r.json().get("likes_count") == 0, r.text[:120])

    # 8. 评论
    r = client.post(f"/api/community/posts/{post_id}/comments", json={"content": "可爱"})
    check("发评论", r.status_code == 200, r.text[:200])
    comment_id = r.json().get("comment_id", "")
    r = client.get(f"/api/community/posts/{post_id}/comments")
    check("评论列表 1 条", r.json().get("count") == 1)

    # 9. 越权：换个用户改不了别人的帖
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={"username": "smoke_b", "display_name": "乙", "password": "pw123456"})
    check("注册第二个用户", r.status_code == 200, r.text[:200])
    r = client.delete(f"/api/community/posts/{post_id}")
    check("他人删帖 403", r.status_code == 403, r.text[:120])
    r = client.post(f"/api/community/posts/{post_id}/like")
    r = client.get(f"/api/community/posts/{post_id}")
    check("他人点赞计数 1", r.json().get("likes_count") == 1, r.text[:120])

    # 10. 识别结果分享
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "smoke_a", "password": "pw123456"})
    from app.backend.database import execute
    from app.backend.services.storage_service import make_id, now_iso
    rid = make_id("rec")
    execute(
        """INSERT INTO recognition_records
           (recognition_id, pet_id, user_id, audio_path, original_filename, prediction_label,
            display_label, confidence, margin, trigger, warning, created_at)
           VALUES (?, ?, ?, '', 'a.wav', 'request_seeking', '诉求·想要东西', 0.82, 0.3, 1, '', ?)""",
        (rid, pet_id, user_a, now_iso()),
    )
    r = client.post("/api/community/posts/from-recognition", json={"recognition_id": rid})
    check("识别分享建帖", r.status_code == 200, r.text[:300])
    shared = r.json()
    check("分享帖类型 recognition", shared.get("post_type") == "recognition")
    check("分享帖可溯源", shared.get("source_recognition_id") == rid)
    check("文案含非医疗声明", "非医疗判断" in (shared.get("content") or ""), shared.get("content"))
    from app.backend.database import fetch_one
    rec = fetch_one("SELECT created_post_id FROM recognition_records WHERE recognition_id = ?", (rid,))
    check("回写 created_post_id", rec and rec["created_post_id"] == shared["post_id"], str(rec))
    tl = fetch_one("SELECT COUNT(*) AS n FROM pet_timeline WHERE related_post_id = ?", (shared["post_id"],))
    check("写入宠物时间线", tl and tl["n"] == 1, str(tl))

    # 11. 删除帖子连带清评论/点赞
    r = client.delete(f"/api/community/posts/{shared['post_id']}")
    check("作者删帖 200", r.status_code == 200, r.text[:120])
    r = client.get(f"/api/community/posts/{shared['post_id']}")
    check("删后 404", r.status_code == 404, r.text[:120])
    left = fetch_one("SELECT COUNT(*) AS n FROM post_comments WHERE post_id = ?", (shared["post_id"],))
    check("评论已连带删除", left and left["n"] == 0, str(left))

    print(f"\n通过 {ok} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：" + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
