r"""社区基础层：帖子 / 点赞 / 评论 / 识别结果分享。

设计口径（与初代 `D:\pet_link\web_app` 的 posts 体系对齐，字段名保持兼容，便于后续移植
follows / friends / conversations 时不用改前端字段）：

- 一切内容都是"某个人发的关于某只宠物的事"，所以 `posts` 同时带 `user_id` 与 `pet_id`。
- 可见性只有 `public` / `friends` / `private` 三个值。当前**没有社交图谱**，
  所以 `friends` 暂时按"仅作者可见"处理（见可见性 SQL 注释），等 follows/friends 建好再放开。
- 识别结果分享必须留溯源：`source_recognition_id` + 回写 `recognition_records.created_post_id`
  + 写一条 `pet_timeline`。这三件事在同一个接口里做完，不允许 App 自己拼。

红线（写进代码而不是只写文档）：
- 识别结果文案只做"行为提示"，不出现诊断式措辞；默认文案由服务端生成，前端不自由拼。
- 低置信（trigger=0）的分享必须带 low_confidence 标记，前端要显示"仅供参考"。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..database import execute, fetch_all, fetch_one
from ..services.current_user_service import require_current_user_id
from ..services.storage_service import make_id, now_iso


router = APIRouter(prefix="/community", tags=["community"])

VISIBILITIES = ("public", "friends", "private")
POST_TYPES = ("note", "recognition", "photo")
MAX_CONTENT = 2000
MAX_COMMENT = 500
FEED_LIMIT_DEFAULT = 20
FEED_LIMIT_MAX = 50

_POST_SELECT = """
SELECT
    p.post_id, p.user_id, p.pet_id, p.content, p.visibility, p.post_type,
    p.image_url, p.source_recognition_id, p.created_at,
    COALESCE(u.display_name, p.user_id) AS author_name,
    COALESCE(u.avatar, '') AS author_avatar,
    COALESCE(pt.name, '') AS pet_name,
    COALESCE(pt.species, '') AS pet_species,
    COALESCE(pt.avatar, '') AS pet_avatar,
    (SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.post_id) AS likes_count,
    (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.post_id) AS comments_count,
    EXISTS(SELECT 1 FROM post_likes l2 WHERE l2.post_id = p.post_id AND l2.user_id = ?) AS liked_by_me
FROM posts p
LEFT JOIN users u ON u.user_id = p.user_id
LEFT JOIN pets pt ON pt.pet_id = p.pet_id
"""


def _clean_text(value: str, field: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=f"{field} too long (max {limit})")
    return text


def _get_post_row(post_id: str, viewer_id: str) -> dict:
    row = fetch_one(_POST_SELECT + " WHERE p.post_id = ?", (viewer_id, post_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if row["visibility"] == "private" and row["user_id"] != viewer_id:
        raise HTTPException(status_code=404, detail="Post not found")
    return row


def _assert_owned_pet(pet_id: str, user_id: str) -> None:
    if not pet_id:
        return
    pet = fetch_one("SELECT pet_id, owner_user_id FROM pets WHERE pet_id = ?", (pet_id,))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet["owner_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Cannot post for another user's pet")


@router.post("/posts")
def create_post(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    content = _clean_text(payload.get("content", ""), "content", MAX_CONTENT)
    visibility = str(payload.get("visibility") or "public").strip().lower()
    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail=f"visibility must be one of {VISIBILITIES}")
    post_type = str(payload.get("post_type") or "note").strip().lower()
    if post_type not in POST_TYPES:
        raise HTTPException(status_code=400, detail=f"post_type must be one of {POST_TYPES}")
    pet_id = str(payload.get("pet_id") or "").strip()
    _assert_owned_pet(pet_id, user_id)
    image_url = str(payload.get("image_url") or "").strip()
    if image_url and not image_url.startswith(("http://", "https://", "/uploads/")):
        raise HTTPException(status_code=400, detail="image_url must be http(s) or /uploads/ path")

    post_id = make_id("post")
    execute(
        """
        INSERT INTO posts (post_id, user_id, pet_id, content, visibility, post_type,
                           image_url, source_recognition_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)
        """,
        (post_id, user_id, pet_id, content, visibility, post_type, image_url, now_iso()),
    )
    return _get_post_row(post_id, user_id)


@router.get("/feed")
def get_feed(request: Request, limit: int = FEED_LIMIT_DEFAULT, before: str = "",
             author: str = "", pet_id: str = "") -> dict:
    """时间线倒序分页。`before` 传上一页最后一条的 created_at。"""
    viewer_id = require_current_user_id(request, allow_legacy_fallback=False)
    limit = max(1, min(limit, FEED_LIMIT_MAX))

    # 可见性：public 或自己的。friends 暂按"仅自己"处理（无社交图谱），接 follows 后改成
    # "public OR 作者在互关列表 OR 作者是自己"。
    where = ["(p.visibility = 'public' OR p.user_id = ?)"]
    params: list = [viewer_id, viewer_id]
    if before:
        where.append("p.created_at < ?")
        params.append(before)
    if author:
        where.append("p.user_id = ?")
        params.append(author)
    if pet_id:
        where.append("p.pet_id = ?")
        params.append(pet_id)

    sql = _POST_SELECT + " WHERE " + " AND ".join(where) + \
        " ORDER BY p.created_at DESC, p.post_id DESC LIMIT ?"
    params.append(limit)
    items = fetch_all(sql, params)
    next_cursor = items[-1]["created_at"] if len(items) == limit else ""
    return {"items": items, "next_cursor": next_cursor, "count": len(items)}


@router.get("/posts/{post_id}")
def get_post(post_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return _get_post_row(post_id, user_id)


@router.delete("/posts/{post_id}")
def delete_post(post_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    row = fetch_one("SELECT post_id, user_id FROM posts WHERE post_id = ?", (post_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post")
    execute("DELETE FROM post_comments WHERE post_id = ?", (post_id,))
    execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
    execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
    return {"deleted": True, "post_id": post_id}


@router.post("/posts/{post_id}/like")
def like_post(post_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    _get_post_row(post_id, user_id)
    existing = fetch_one("SELECT like_id FROM post_likes WHERE post_id = ? AND user_id = ?",
                         (post_id, user_id))
    if existing is None:
        execute(
            "INSERT INTO post_likes (like_id, post_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (make_id("like"), post_id, user_id, now_iso()),
        )
    count = fetch_one("SELECT COUNT(*) AS n FROM post_likes WHERE post_id = ?", (post_id,))
    return {"post_id": post_id, "liked": True, "likes_count": count["n"] if count else 0}


@router.delete("/posts/{post_id}/like")
def unlike_post(post_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    execute("DELETE FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    count = fetch_one("SELECT COUNT(*) AS n FROM post_likes WHERE post_id = ?", (post_id,))
    return {"post_id": post_id, "liked": False, "likes_count": count["n"] if count else 0}


@router.get("/posts/{post_id}/comments")
def list_comments(post_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    _get_post_row(post_id, user_id)
    items = fetch_all(
        """
        SELECT c.comment_id, c.post_id, c.user_id, c.content, c.created_at,
               COALESCE(u.display_name, c.user_id) AS author_name,
               COALESCE(u.avatar, '') AS author_avatar
        FROM post_comments c
        LEFT JOIN users u ON u.user_id = c.user_id
        WHERE c.post_id = ?
        ORDER BY c.created_at ASC
        """,
        (post_id,),
    )
    return {"items": items, "count": len(items)}


@router.post("/posts/{post_id}/comments")
def create_comment(post_id: str, payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    _get_post_row(post_id, user_id)
    content = _clean_text(payload.get("content", ""), "content", MAX_COMMENT)
    comment_id = make_id("comment")
    execute(
        "INSERT INTO post_comments (comment_id, post_id, user_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (comment_id, post_id, user_id, content, now_iso()),
    )
    return fetch_one(
        """
        SELECT c.comment_id, c.post_id, c.user_id, c.content, c.created_at,
               COALESCE(u.display_name, c.user_id) AS author_name,
               COALESCE(u.avatar, '') AS author_avatar
        FROM post_comments c LEFT JOIN users u ON u.user_id = c.user_id
        WHERE c.comment_id = ?
        """,
        (comment_id,),
    )


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    row = fetch_one(
        """
        SELECT c.comment_id, c.user_id, p.user_id AS post_owner_id
        FROM post_comments c JOIN posts p ON p.post_id = c.post_id
        WHERE c.comment_id = ?
        """,
        (comment_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if user_id not in (row["user_id"], row["post_owner_id"]):
        raise HTTPException(status_code=403, detail="Only the comment author or post owner can delete")
    execute("DELETE FROM post_comments WHERE comment_id = ?", (comment_id,))
    return {"deleted": True, "comment_id": comment_id}


@router.post("/posts/from-recognition")
def create_post_from_recognition(payload: dict, request: Request) -> dict:
    """把一次识别结果分享成帖子：建帖 + 回写识别记录 + 写宠物时间线，一次做完。

    请求：{"recognition_id": "...", "content": "可选，自定义文案", "visibility": "public"}
    默认文案由服务端生成，避免前端把标签拼成诊断式措辞。
    """
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    recognition_id = str(payload.get("recognition_id") or "").strip()
    if not recognition_id:
        raise HTTPException(status_code=400, detail="recognition_id is required")

    record = fetch_one("SELECT * FROM recognition_records WHERE recognition_id = ?", (recognition_id,))
    if record is None:
        raise HTTPException(status_code=404, detail="Recognition record not found")
    if (record.get("user_id") or "") not in ("", user_id):
        raise HTTPException(status_code=403, detail="Cannot share another user's recognition record")

    visibility = str(payload.get("visibility") or "public").strip().lower()
    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail=f"visibility must be one of {VISIBILITIES}")

    label = (record.get("display_label") or record.get("prediction_label") or "未知").strip()
    confidence = float(record.get("confidence") or 0.0)
    triggered = bool(record.get("trigger"))
    custom = str(payload.get("content") or "").strip()
    if custom:
        content = _clean_text(custom, "content", MAX_CONTENT)
    else:
        tail = "（行为提示，非医疗判断）"
        content = f"刚听到一声：{label}，置信 {confidence * 100:.0f}%{'' if triggered else '，仅供参考'}{tail}"

    post_id = make_id("post")
    created_at = now_iso()
    execute(
        """
        INSERT INTO posts (post_id, user_id, pet_id, content, visibility, post_type,
                           image_url, source_recognition_id, created_at)
        VALUES (?, ?, ?, ?, ?, 'recognition', '', ?, ?)
        """,
        (post_id, user_id, record.get("pet_id") or "", content, visibility,
         recognition_id, created_at),
    )
    execute("UPDATE recognition_records SET created_post_id = ? WHERE recognition_id = ?",
            (post_id, recognition_id))

    pet_id = record.get("pet_id") or ""
    if pet_id:
        execute(
            """
            INSERT INTO pet_timeline (timeline_id, pet_id, event_type, title, content,
                                      related_post_id, related_recognition_id, created_at)
            VALUES (?, ?, 'recognition_shared', ?, ?, ?, ?, ?)
            """,
            (make_id("timeline"), pet_id, "分享了一次识别结果", content,
             post_id, recognition_id, created_at),
        )

    post = _get_post_row(post_id, user_id)
    post["low_confidence"] = not triggered
    return post
